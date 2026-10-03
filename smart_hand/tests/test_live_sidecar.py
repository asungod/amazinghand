import copy
import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))

from live_sidecar import (  # noqa: E402
    LiveWebSidecar,
    TelemetryUnavailableError,
    WebSignIntentLatch,
    WebTrainIntentLatch,
)
from telemetry_schema import validate_telemetry  # noqa: E402
from web_stream import LatestFrameStore  # noqa: E402


class FakeServer:
    def __init__(
        self,
        telemetry_provider,
        train_request_handler=None,
        train_status_provider=None,
    ):
        self.telemetry_provider = telemetry_provider
        self.train_request_handler = train_request_handler
        self.train_status_provider = train_status_provider
        self.frames = LatestFrameStore()
        self.start_calls = []
        self.poll_calls = []
        self.last_fault = None
        self.close_calls = 0
        self.start_result = True

    def start(self, host, port):
        self.start_calls.append((host, port))
        if not self.start_result:
            self.last_fault = "socket_start_failed:OSError"
        return self.start_result

    def publish_jpeg(self, jpeg, now_ms):
        return self.frames.publish(jpeg, now_ms)

    def poll(self, max_accepts, max_client_writes):
        self.poll_calls.append((max_accepts, max_client_writes))
        return 1

    def close(self):
        self.close_calls += 1


class ServerFactory:
    def __init__(self, start_result=True):
        self.start_result = start_result
        self.created = 0
        self.server = None

    def __call__(self, **kwargs):
        self.created += 1
        self.server = FakeServer(**kwargs)
        self.server.start_result = self.start_result
        return self.server


class GoodFrame:
    def __init__(self):
        self.calls = 0

    def to_jpeg(self):
        self.calls += 1
        return type("Jpeg", (), {"to_bytes": lambda _self: b"jpeg"})()


class BrokenFrame:
    def to_jpeg(self):
        raise RuntimeError("encoder unavailable")


class BrokenBytesFrame:
    @staticmethod
    def to_jpeg():
        return type(
            "BrokenJpeg", (), {
                "to_bytes": lambda _self: (_ for _ in ()).throw(ValueError("copy failed")),
            }
        )()


def runtime_state():
    return {
        "vision_phase": "TARGET",
        "vision_source": type(
            "Vision", (), {
                "last_inference_ms": 17,
                "last_objects": [object(), object()],
                "inference_fps": lambda _self: 58,
            }
        )(),
        "vision_scheduler": type("Scheduler", (), {"last_process_ms": 0})(),
        "vision_stale_after_ms": 750,
        "vision_mode": "yolo11",
        "vision_model": "yolo11n.mud",
        "target_payload": (39, 100, 100, 40, 50, 91),
        "target_labels": {39: "bottle"},
        "hand_source": None,
        "train_controller": type("Train", (), {"state": "QUEUED"})(),
        "imitation_controller": type(
            "Imitation", (), {
                "state": "IDLE", "repetitions": 0, "goal_repetitions": 5,
                "completion_percent": lambda _self: 0,
                "quality_tracker": type("Quality", (), {"summary": lambda _self: {}})(),
            }
        )(),
        "authority": {
            "snapshot": {
                "ver": 1, "link_online": True, "have_vision": True,
                "vision_stale": False,
            },
            "last_status_ms": 0,
        },
        "ack_monitor": type("Ack", (), {"last_rtt_ms": 21, "consecutive_timeouts": 0})(),
    }


class LiveSidecarTests(unittest.TestCase):
    def test_sign_intent_expires_fail_closed_after_ttl(self):
        clock = {"now": 100}
        latch = WebSignIntentLatch(
            now_ms_provider=lambda: clock["now"],
            elapsed_ms=lambda now, previous: now - previous,
            ttl_ms=2000,
        )
        self.assertEqual(latch.enqueue("start"), 1)
        clock["now"] = 2100
        self.assertIsNone(latch.take())
        self.assertEqual(latch.status()["state"], "rejected")
        self.assertEqual(latch.status()["reason"], "request_expired")

    def test_sign_intent_returns_without_internal_timestamp(self):
        latch = WebSignIntentLatch(now_ms_provider=lambda: 10)
        self.assertEqual(latch.enqueue("select", "basic_fist"), 1)
        self.assertEqual(
            latch.take(now_ms=11),
            {"request_id": 1, "action": "select", "lesson_id": "basic_fist"},
        )

    def test_web_train_latch_is_single_slot_and_submission_locked(self):
        latch = WebTrainIntentLatch()
        self.assertEqual(latch.status()["state"], "idle")
        self.assertEqual(latch.enqueue(), 1)
        self.assertIsNone(latch.enqueue())
        self.assertEqual(latch.take(), 1)
        self.assertTrue(latch.submitted(1))
        self.assertIsNone(latch.enqueue())
        latch.set_submission_ready(True)
        self.assertEqual(
            latch.status(),
            {
                "request_id": 1,
                "state": "idle",
                "reason": "ready_for_request",
                "can_submit": False,
                "availability_reason": "availability_unknown",
            },
        )
        self.assertEqual(latch.enqueue(), 2)
        self.assertEqual(latch.take(), 2)
        self.assertTrue(latch.reject(2, "not_bottle"))
        self.assertEqual(
            latch.status(),
            {
                "request_id": 2,
                "state": "rejected",
                "reason": "not_bottle",
                "can_submit": False,
                "availability_reason": "availability_unknown",
            },
        )

    def test_web_train_availability_is_main_loop_owned_and_fail_closed(self):
        latch = WebTrainIntentLatch()
        reasons = (
            "bottle_not_stable", "not_bottle", "bottle_confidence_low",
            "titan_status_stale", "titan_link_offline", "titan_gate_unavailable",
            "uart_degraded", "train_busy",
        )
        for reason in reasons:
            latch.set_availability(False, reason)
            self.assertEqual(latch.status()["can_submit"], False)
            self.assertEqual(latch.status()["availability_reason"], reason)
        latch.set_availability(True, "must_not_leak")
        self.assertEqual(latch.status()["can_submit"], True)
        self.assertIsNone(latch.status()["availability_reason"])
        latch.set_availability("true", "not_safe")
        self.assertEqual(latch.status()["can_submit"], False)
        self.assertEqual(latch.status()["availability_reason"], "availability_unknown")

    def test_sidecar_web_intent_methods_do_not_depend_on_hardware(self):
        sidecar = LiveWebSidecar(runtime_state, server_factory=ServerFactory())
        response = sidecar.enqueue_web_train()
        self.assertEqual(response, {"request_id": 1, "state": "queued_for_main"})
        self.assertEqual(sidecar.take_web_train_intent(), 1)
        self.assertTrue(sidecar.note_web_train_rejected(1, "not_bottle"))
        self.assertEqual(sidecar.web_train_status()["reason"], "not_bottle")
        sidecar.set_web_train_availability(False, "titan_status_stale")
        self.assertEqual(
            sidecar.web_train_status()["availability_reason"], "titan_status_stale"
        )
    def test_start_failure_safely_degrades_without_encoding_or_poll_io(self):
        factory = ServerFactory(start_result=False)
        sidecar = LiveWebSidecar(runtime_state, server_factory=factory)

        self.assertFalse(sidecar.start())
        frame = GoodFrame()
        self.assertFalse(sidecar.offer(frame, 0))
        self.assertEqual(frame.calls, 0)
        self.assertEqual(sidecar.poll(0), 0)
        self.assertEqual(factory.server.poll_calls, [])
        self.assertEqual(sidecar.stream_fault, "socket_start_failed:OSError")

    def test_publish_uses_to_jpeg_to_bytes_and_caps_cadence_at_five_fps(self):
        factory = ServerFactory()
        sidecar = LiveWebSidecar(runtime_state, server_factory=factory)
        self.assertTrue(sidecar.start())
        frame = GoodFrame()

        self.assertTrue(sidecar.offer(frame, 0))
        self.assertFalse(sidecar.offer(frame, 199))
        self.assertTrue(sidecar.offer(frame, 200))

        self.assertEqual(frame.calls, 2)
        self.assertEqual(factory.server.frames.snapshot()[1], b"jpeg")
        self.assertEqual(factory.server.frames.published, 2)

    def test_encoding_fault_is_contained_and_exposed_as_strict_telemetry(self):
        factory = ServerFactory()
        sidecar = LiveWebSidecar(runtime_state, server_factory=factory)
        sidecar.start()

        self.assertFalse(sidecar.offer(BrokenFrame(), 0))
        document = json.loads(sidecar.telemetry_json().decode("utf-8"))

        self.assertIs(validate_telemetry(document), document)
        self.assertEqual(document["frame"]["encoding_fault"], "jpeg_encode_failed:RuntimeError")
        self.assertTrue(document["health"]["faults"]["jpeg"])
        self.assertEqual(document["ai"]["target"], "bottle")
        self.assertEqual(document["ai"]["inference_fps"], 58)
        self.assertEqual(document["titan"]["rtt_ms"], 21)

    def test_inference_fps_zero_is_preserved(self):
        state = runtime_state()
        state["vision_source"].inference_fps = lambda: 0
        sidecar = LiveWebSidecar(lambda: state, server_factory=ServerFactory())
        sidecar.start()
        sidecar.poll(0)

        document = json.loads(sidecar.telemetry_json().decode("utf-8"))
        self.assertIs(validate_telemetry(document), document)
        self.assertEqual(document["ai"]["inference_fps"], 0)

    def test_inference_fps_exception_is_unreported_and_schema_remains_strict(self):
        state = runtime_state()

        def fail_fps():
            raise RuntimeError("counter unavailable")

        state["vision_source"].inference_fps = fail_fps
        sidecar = LiveWebSidecar(lambda: state, server_factory=ServerFactory())
        sidecar.start()
        sidecar.poll(0)

        document = json.loads(sidecar.telemetry_json().decode("utf-8"))
        self.assertIs(validate_telemetry(document), document)
        self.assertIsNone(document["ai"]["inference_fps"])

    def test_to_bytes_failure_is_also_contained(self):
        factory = ServerFactory()
        sidecar = LiveWebSidecar(runtime_state, server_factory=factory)
        sidecar.start()

        self.assertFalse(sidecar.offer(BrokenBytesFrame(), 0))
        self.assertEqual(sidecar.encoding_fault, "jpeg_encode_failed:ValueError")

    def test_status_timeout_clears_authority_fields(self):
        factory = ServerFactory()
        sidecar = LiveWebSidecar(runtime_state, server_factory=factory)
        sidecar.start()
        sidecar.poll(1500)

        document = json.loads(sidecar.telemetry_json().decode("utf-8"))
        self.assertTrue(document["health"]["stale"]["titan_status"])
        self.assertIsNone(document["titan"]["action"])
        self.assertIsNone(document["titan"]["reason"])
        self.assertEqual(document["titan"]["gate"], {"present": None, "armed": None, "fault": None})

    def test_poll_is_explicitly_bounded_and_runtime_input_is_not_modified(self):
        state = runtime_state()
        state["authority"] = {"snapshot": {"ver": 1, "link_online": True}, "last_status_ms": 0}
        before = copy.deepcopy(state["authority"])
        factory = ServerFactory()
        sidecar = LiveWebSidecar(lambda: state, server_factory=factory)
        sidecar.start()

        self.assertEqual(sidecar.poll(1), 1)
        self.assertEqual(factory.server.poll_calls, [(1, 1)])
        self.assertEqual(state["authority"], before)

    def test_telemetry_encode_diagnostic_is_rate_limited_and_stable(self):
        sidecar = LiveWebSidecar(runtime_state, server_factory=ServerFactory())
        output = io.StringIO()
        with patch("live_sidecar.telemetry_json", side_effect=TypeError("unsupported")):
            with contextlib.redirect_stdout(output):
                for _ in range(2):
                    with self.assertRaises(TelemetryUnavailableError) as raised:
                        sidecar.telemetry_json()
                    self.assertEqual(raised.exception.code, "telemetry_encode_TypeError")

        self.assertEqual(output.getvalue().count("live web telemetry fault"), 1)
        self.assertIn("code=telemetry_encode_TypeError", output.getvalue())

    def test_build_value_errors_are_mapped_to_safe_field_codes(self):
        cases = {
            "elapsed_ms must be non-negative integer milliseconds": "elapsed_ms",
            "now_ms must be non-negative integer milliseconds": "now_ms",
            "last_rtt_ms must be non-negative integer milliseconds": "rtt",
            "frame.age_ms must be non-negative integer milliseconds": "frame",
            "ai.inference_ms must be non-negative integer milliseconds": "ai",
            "hand.pose must be text or None": "hand",
            "training.phase is invalid": "training",
            "unknown training.phase": "training",
            "link.state is invalid": "link",
            "unknown titan.link": "link",
            "faults.jpeg must be boolean": "faults",
            "authority must be an object or None": "authority",
            "unsupported telemetry schema or version": "schema",
            "unclassified build error": "other",
        }
        for message, group in cases.items():
            with self.subTest(group=group):
                sidecar = LiveWebSidecar(runtime_state, server_factory=ServerFactory())
                with patch.object(sidecar.runtime, "build", side_effect=ValueError(message)):
                    with contextlib.redirect_stdout(io.StringIO()):
                        with self.assertRaises(TelemetryUnavailableError) as raised:
                            sidecar.telemetry_json()
                self.assertEqual(
                    raised.exception.code,
                    "telemetry_build_ValueError_{}".format(group),
                )

    def test_invalid_elapsed_values_map_to_the_same_safe_code(self):
        for invalid in (100.5, float("nan"), -1):
            with self.subTest(invalid=invalid):
                sidecar = LiveWebSidecar(
                    runtime_state,
                    elapsed_ms=lambda _now, _previous: invalid,
                    server_factory=ServerFactory(),
                )
                sidecar.poll(100)
                with contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(TelemetryUnavailableError) as raised:
                        sidecar.telemetry_json()
                self.assertEqual(
                    raised.exception.code,
                    "telemetry_build_ValueError_elapsed_ms",
                )

    def test_integral_float_ticks_keep_published_frame_and_vision_fresh(self):
        sidecar = LiveWebSidecar(
            runtime_state,
            elapsed_ms=lambda _now, _previous: 200.0,
            server_factory=ServerFactory(),
        )
        sidecar.start()
        self.assertTrue(sidecar.offer(GoodFrame(), 1000.0))
        sidecar.poll(1200.0)

        document = json.loads(sidecar.telemetry_json().decode("utf-8"))
        self.assertEqual(document["frame"]["age_ms"], 200)
        self.assertFalse(document["frame"]["stale"])
        self.assertFalse(document["health"]["stale"]["vision"])

    def test_zero_tick_values_are_preserved(self):
        sidecar = LiveWebSidecar(
            runtime_state,
            elapsed_ms=lambda _now, _previous: 0.0,
            server_factory=ServerFactory(),
        )
        sidecar.start()
        self.assertTrue(sidecar.offer(GoodFrame(), 0.0))
        sidecar.poll(0.0)

        document = json.loads(sidecar.telemetry_json().decode("utf-8"))
        self.assertEqual(document["frame"]["age_ms"], 0)
        self.assertFalse(document["frame"]["stale"])
        self.assertFalse(document["health"]["stale"]["vision"])

    def test_invalid_ticks_fail_stale_without_throwing(self):
        for invalid in (100.5, float("nan"), float("inf"), -1, True):
            with self.subTest(invalid=invalid):
                sidecar = LiveWebSidecar(
                    runtime_state,
                    elapsed_ms=lambda _now, _previous: invalid,
                    server_factory=ServerFactory(),
                )
                sidecar.start()
                self.assertTrue(sidecar.offer(GoodFrame(), 10))
                self.assertEqual(sidecar.poll(20), 1)
                inputs = sidecar._runtime_inputs(20)
                self.assertTrue(inputs["frame"]["stale"])

    def test_invalid_now_ms_is_zeroed_but_always_fail_stale(self):
        sidecar = LiveWebSidecar(
            runtime_state,
            elapsed_ms=lambda _now, _previous: 0,
            server_factory=ServerFactory(),
        )
        sidecar.start()
        self.assertTrue(sidecar.offer(GoodFrame(), 0))
        self.assertEqual(sidecar.poll(float("nan")), 1)

        document = json.loads(sidecar.telemetry_json().decode("utf-8"))
        self.assertEqual(sidecar.last_now_ms, 0)
        self.assertTrue(document["frame"]["stale"])
        self.assertFalse(document["health"]["stale"]["vision"])

    def test_integer_subclass_ticks_are_compatible(self):
        class MaixInteger(int):
            pass

        sidecar = LiveWebSidecar(
            runtime_state,
            elapsed_ms=lambda _now, _previous: MaixInteger(0),
            server_factory=ServerFactory(),
        )
        sidecar.start()
        self.assertTrue(sidecar.offer(GoodFrame(), MaixInteger(0)))
        sidecar.poll(MaixInteger(0))

        document = json.loads(sidecar.telemetry_json().decode("utf-8"))
        self.assertEqual(document["frame"]["age_ms"], 0)
        self.assertFalse(document["frame"]["stale"])

    def test_local_scheduler_freshness_cannot_clear_titan_vision_stale(self):
        state = runtime_state()
        state["authority"]["snapshot"]["vision_stale"] = True
        sidecar = LiveWebSidecar(
            lambda: state,
            elapsed_ms=lambda _now, _previous: 0,
            server_factory=ServerFactory(),
        )
        sidecar.start()
        sidecar.poll(0)

        document = json.loads(sidecar.telemetry_json().decode("utf-8"))
        self.assertTrue(document["health"]["stale"]["vision"])


if __name__ == "__main__":
    unittest.main()
