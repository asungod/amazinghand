import copy
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))

from link_monitor import AckMonitor  # noqa: E402
from status_snapshot import (  # noqa: E402
    ACTION_CYLINDRICAL,
    FAULT_NONE,
    POSE_OK,
    REASON_ACCEPTED,
    STATUS_VERSION,
    SUBMIT_SUBMITTED,
    pack_flags,
)
from telemetry_runtime import TelemetryRuntimeAdapter, build_runtime_telemetry  # noqa: E402
from telemetry_schema import validate_telemetry  # noqa: E402


def snapshot(*, gate_present=True, link_online=True):
    return {
        "ver": STATUS_VERSION,
        "flags": pack_flags(
            link_online=link_online,
            have_vision=True,
            vision_stale=False,
            have_last_rx=True,
            gate_present=gate_present,
            gate_armed=True,
            gate_fault=False,
            have_actionable=True,
        ),
        "link_online": link_online,
        "have_vision": True,
        "vision_stale": False,
        "have_last_rx": True,
        "gate_present": gate_present,
        "gate_armed": True if gate_present else None,
        "gate_fault": False if gate_present else None,
        "have_actionable": True,
        "last_rx_seq": 3,
        "action": ACTION_CYLINDRICAL,
        "reason": REASON_ACCEPTED,
        "pose": POSE_OK,
        "submit": SUBMIT_SUBMITTED if gate_present else 0,
        "fault": FAULT_NONE,
        "tx_seq": 9,
    }


class TelemetryRuntimeTests(unittest.TestCase):
    def test_complete_normal_runtime_state_is_strict_v1(self):
        monitor = AckMonitor(1000)
        monitor.last_rtt_ms = 28
        document = build_runtime_telemetry(
            2000,
            frame={"sequence": 7, "available": True, "stale": False, "age_ms": 20, "dropped": 3},
            ai={"model": "yolo11n", "mode": "yolo11", "confidence_pct": 96, "detections": 2, "inference_ms": 31, "inference_fps": 32.2, "target": "bottle"},
            hand={"pose": "OPEN", "openness_pct": 91, "valid_frame_pct": 98},
            training={"phase": "running", "repetitions": 2, "goal_repetitions": 5, "completion_pct": 40, "quality": {"status": "OK", "rhythm": "NORMAL", "hold": "OK"}},
            vision={"stale": False},
            authority={"snapshot": snapshot(), "last_status_ms": 1000},
            ack_monitor=monitor,
            faults={"vision": False, "jpeg": False, "stream": False},
        )

        self.assertIs(validate_telemetry(document), document)
        self.assertEqual(document["titan"], {"link": "online", "rtt_ms": 28, "action": "CYLINDRICAL", "reason": "accepted", "gate": {"present": True, "armed": True, "fault": False}})
        self.assertEqual(document["health"], {"stale": {"frame": False, "vision": False, "titan_status": False}, "faults": {"vision": False, "uart": False, "jpeg": False, "stream": False}})

    def test_zero_values_are_preserved_including_uart_rtt(self):
        monitor = AckMonitor(1000)
        monitor.last_rtt_ms = 0
        document = build_runtime_telemetry(
            0,
            frame={"sequence": 0, "available": True, "stale": False, "age_ms": 0, "dropped": 0},
            ai={"confidence_pct": 0, "detections": 0, "inference_ms": 0, "inference_fps": 0},
            hand={"openness_pct": 0, "valid_frame_pct": 0},
            training={"repetitions": 0, "goal_repetitions": 0, "completion_pct": 0},
            vision={"stale": False},
            authority={"snapshot": snapshot(), "last_status_ms": 0},
            ack_monitor=monitor,
        )

        self.assertEqual(document["frame"]["sequence"], 0)
        self.assertEqual(document["ai"]["detections"], 0)
        self.assertEqual(document["training"]["completion_pct"], 0)
        self.assertEqual(document["titan"]["rtt_ms"], 0)

    def test_stale_status_clears_authority_fields(self):
        monitor = AckMonitor(1000)
        monitor.acked = 9
        document = build_runtime_telemetry(
            2500,
            authority={"snapshot": snapshot(), "last_status_ms": 1000},
            ack_monitor=monitor,
            status_timeout_ms=1500,
        )

        self.assertTrue(document["health"]["stale"]["titan_status"])
        self.assertIsNone(document["titan"]["action"])
        self.assertIsNone(document["titan"]["reason"])
        self.assertEqual(document["titan"]["gate"], {"present": None, "armed": None, "fault": None})
        self.assertEqual(document["titan"]["link"], "unknown")
        self.assertTrue(document["health"]["stale"]["vision"])

    def test_vision_stale_uses_fresh_titan_status_not_local_scheduler(self):
        titan_stale = snapshot()
        titan_stale["have_vision"] = False
        titan_stale["vision_stale"] = True
        document = build_runtime_telemetry(
            100,
            authority={"snapshot": titan_stale, "last_status_ms": 0},
            # This local input is deliberately ignored for health.vision.
            vision={"stale": False},
        )

        self.assertTrue(document["health"]["stale"]["vision"])

    def test_fresh_actionable_titan_candidate_clears_vision_stale(self):
        document = build_runtime_telemetry(
            100,
            authority={"snapshot": snapshot(), "last_status_ms": 0},
            vision={"stale": True},
        )

        self.assertFalse(document["health"]["stale"]["vision"])

    def test_missing_or_nonboolean_titan_vision_status_fails_stale(self):
        for have_vision, vision_stale in ((None, False), (True, None), (True, 0)):
            with self.subTest(have_vision=have_vision, vision_stale=vision_stale):
                state = snapshot()
                if have_vision is None:
                    del state["have_vision"]
                else:
                    state["have_vision"] = have_vision
                state["vision_stale"] = vision_stale
                document = build_runtime_telemetry(
                    100,
                    authority={"snapshot": state, "last_status_ms": 0},
                )
                self.assertTrue(document["health"]["stale"]["vision"])

    def test_unknown_gate_is_null_without_hiding_fresh_action(self):
        document = build_runtime_telemetry(
            100,
            authority={"snapshot": snapshot(gate_present=False), "last_status_ms": 0},
        )

        self.assertFalse(document["health"]["stale"]["titan_status"])
        self.assertEqual(document["titan"]["action"], "CYLINDRICAL")
        self.assertEqual(document["titan"]["gate"], {"present": None, "armed": None, "fault": None})

    def test_rtt_is_none_without_valid_sample_and_zero_is_valid(self):
        missing = build_runtime_telemetry(1, authority={"snapshot": snapshot(), "last_status_ms": 0})
        zero = build_runtime_telemetry(
            1,
            authority={"snapshot": snapshot(), "last_status_ms": 0},
            link={"last_rtt_ms": 0},
        )

        self.assertIsNone(missing["titan"]["rtt_ms"])
        self.assertEqual(zero["titan"]["rtt_ms"], 0)

    def test_uart_fault_uses_current_state_not_historical_counters(self):
        monitor = AckMonitor(1000)
        monitor.timed_out = 4
        monitor.send_failures = 3
        monitor.max_consecutive_timeouts = 4
        monitor.consecutive_timeouts = 0
        healthy = build_runtime_telemetry(
            100,
            authority={"snapshot": snapshot(), "last_status_ms": 0},
            ack_monitor=monitor,
        )
        failed_now = build_runtime_telemetry(
            100,
            authority={"snapshot": snapshot(), "last_status_ms": 0},
            ack_monitor=monitor,
            link={"consecutive_timeouts": 1},
        )

        self.assertFalse(healthy["health"]["faults"]["uart"])
        self.assertEqual(healthy["titan"]["link"], "online")
        self.assertTrue(failed_now["health"]["faults"]["uart"])
        self.assertEqual(failed_now["titan"]["link"], "degraded")

    def test_inputs_are_not_modified_and_only_current_faults_are_used(self):
        inputs = {
            "frame": {"sequence": 4, "available": True, "stale": False, "raw_jpeg": b"private"},
            "vision": {"stale": False, "last_error": "historic"},
            "authority": {"snapshot": snapshot(), "last_status_ms": 0},
            "faults": {"vision": False, "jpeg": False, "stream": False, "last_fault": "historic"},
        }
        original = copy.deepcopy(inputs)
        document = build_runtime_telemetry(100, **inputs)

        self.assertEqual(inputs, original)
        self.assertNotIn("raw_jpeg", document["frame"])
        self.assertFalse(document["health"]["faults"]["jpeg"])
        self.assertFalse(document["health"]["faults"]["stream"])

    def test_adapter_has_fixed_timing_and_remains_schema_strict(self):
        adapter = TelemetryRuntimeAdapter(status_timeout_ms=10)
        document = adapter.build(10, authority={"snapshot": snapshot(), "last_status_ms": 0})
        self.assertTrue(document["health"]["stale"]["titan_status"])
        with self.assertRaises(ValueError):
            adapter.build(1, status_timeout_ms=1)

    def test_integral_float_milliseconds_are_canonicalized_for_maix_ticks(self):
        monitor = AckMonitor(1000)
        monitor.last_rtt_ms = 28.0
        document = build_runtime_telemetry(
            2000.0,
            frame={"sequence": 1, "available": True, "stale": False, "age_ms": 20.0},
            ai={"inference_ms": 31.0},
            authority={"snapshot": snapshot(), "last_status_ms": 1000.0},
            ack_monitor=monitor,
            elapsed_ms=lambda _now, _previous: 100.0,
        )

        self.assertIs(validate_telemetry(document), document)
        self.assertEqual(document["timestamp_ms"], 2000)
        self.assertEqual(document["frame"]["age_ms"], 20)
        self.assertEqual(document["ai"]["inference_ms"], 31)
        self.assertEqual(document["titan"]["rtt_ms"], 28)

    def test_fractional_nan_and_negative_elapsed_ms_fail_closed(self):
        for invalid in (100.5, float("nan"), -1):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "elapsed_ms"):
                    build_runtime_telemetry(
                        200,
                        authority={"snapshot": snapshot(), "last_status_ms": 0},
                        elapsed_ms=lambda _now, _previous: invalid,
                    )

    def test_integer_subclass_milliseconds_are_normalized(self):
        class MaixInteger(int):
            pass

        monitor = AckMonitor(1000)
        monitor.last_rtt_ms = MaixInteger(28)
        document = build_runtime_telemetry(
            MaixInteger(200),
            frame={"age_ms": MaixInteger(20)},
            ai={"inference_ms": MaixInteger(31)},
            authority={"snapshot": snapshot(), "last_status_ms": MaixInteger(0)},
            ack_monitor=monitor,
            elapsed_ms=lambda _now, _previous: MaixInteger(100),
        )

        self.assertEqual(document["timestamp_ms"], 200)
        self.assertEqual(document["frame"]["age_ms"], 20)
        self.assertEqual(document["ai"]["inference_ms"], 31)
        self.assertEqual(document["titan"]["rtt_ms"], 28)


if __name__ == "__main__":
    unittest.main()
