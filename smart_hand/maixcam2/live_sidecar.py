"""Bounded, opt-in web-preview integration for the MaixCAM2 main loop.

This module performs no Maix, camera, UART, or socket work when imported.
``LiveWebSidecar.start`` is the only operation which can bind the optional
HTTP listener.  Its producer hook accepts only an already-annotated frame and
is deliberately isolated from the vision/UART loop: all encoder and network
errors are recorded locally and never propagated.
"""

from telemetry_runtime import TelemetryRuntimeAdapter
from telemetry_schema import telemetry_json
from web_stream import PreviewServer


DEFAULT_PUBLISH_INTERVAL_MS = 200
DEFAULT_FRAME_STALE_MS = 1000


class WebTrainIntentLatch:
    """One-slot, main-loop-owned web intent transport with no hardware access."""

    def __init__(self):
        self._next_request_id = 1
        self._pending_request_id = None
        self._submission_locked = False
        self._status = {
            "request_id": 0,
            "state": "idle",
            "reason": "no_request",
        }
        self._availability = {
            "can_submit": False,
            "availability_reason": "availability_unknown",
        }

    def enqueue(self):
        if self._pending_request_id is not None or self._submission_locked:
            return None
        request_id = self._next_request_id
        self._next_request_id = 1 if request_id >= 0x7FFFFFFF else request_id + 1
        self._pending_request_id = request_id
        self._status = {
            "request_id": request_id,
            "state": "pending",
            "reason": None,
        }
        return request_id

    def take(self):
        request_id = self._pending_request_id
        self._pending_request_id = None
        return request_id

    def reject(self, request_id, reason):
        if request_id != self._status["request_id"]:
            return False
        self._status = {
            "request_id": request_id,
            "state": "rejected",
            "reason": str(reason),
        }
        return True

    def submitted(self, request_id):
        if request_id != self._status["request_id"]:
            return False
        self._submission_locked = True
        self._status = {
            "request_id": request_id,
            "state": "submitted",
            "reason": "submitted_to_titan",
        }
        return True

    def set_submission_ready(self, ready):
        if ready and self._submission_locked:
            self._submission_locked = False
            if self._status["state"] == "submitted":
                # Ready only means the main-loop gate has re-opened.  It never
                # claims that the earlier Titan request executed successfully.
                self._status = {
                    "request_id": self._status["request_id"],
                    "state": "idle",
                    "reason": "ready_for_request",
                }

    def set_availability(self, can_submit, reason):
        """Publish only main-loop-computed request readiness, never execution."""
        if type(can_submit) is not bool:
            can_submit = False
            reason = "availability_unknown"
        elif can_submit:
            reason = None
        elif not isinstance(reason, str) or not reason:
            reason = "availability_unknown"
        self._availability = {
            "can_submit": can_submit,
            "availability_reason": reason,
        }

    def status(self):
        status = dict(self._status)
        status.update(self._availability)
        return status


class WebSignIntentLatch:
    """Bounded transport for sign ``select/start/cancel/review`` commands.

    The latch is deliberately controller-agnostic.  HTTP callbacks only
    validate/record a command; the Maix main loop must call ``take`` and
    perform lesson, Titan-link, and freshness checks before invoking any
    controller or hardware-facing code.
    """

    _ACTIONS = ("select", "start", "cancel", "review")

    def __init__(self, now_ms_provider=None, elapsed_ms=None, ttl_ms=2000):
        if type(ttl_ms) is not int or ttl_ms < 1:
            raise ValueError("ttl_ms must be a positive integer")
        self._next_request_id = 1
        self._pending = None
        self._now_ms_provider = now_ms_provider
        self._elapsed_ms = elapsed_ms
        self._ttl_ms = ttl_ms
        self._status = {
            "request_id": 0,
            "state": "idle",
            "reason": "no_request",
        }

    def enqueue(self, action, lesson_id=None, session_token=None, manual_confirm=False):
        if action not in self._ACTIONS or self._pending is not None:
            return None
        if action in ("select", "review"):
            if not isinstance(lesson_id, str) or not lesson_id or len(lesson_id) > 64:
                return None
        elif lesson_id is not None:
            return None
        if action == "review":
            if (type(session_token) is not int or not 1 <= session_token <= 0x7FFFFFFF or
                    manual_confirm is not True):
                return None
        elif session_token is not None or manual_confirm is not False:
            return None
        request_id = self._next_request_id
        self._next_request_id = 1 if request_id >= 0x7FFFFFFF else request_id + 1
        self._pending = {
            "request_id": request_id,
            "action": action,
            "lesson_id": lesson_id,
            "enqueued_ms": self._now_ms(),
        }
        if action == "review":
            self._pending.update(session_token=session_token, manual_confirm=True)
        self._status = {
            "request_id": request_id,
            "state": "pending",
            "reason": None,
            "action": action,
        }
        if lesson_id is not None:
            self._status["lesson_id"] = lesson_id
        return request_id

    def _now_ms(self):
        if not callable(self._now_ms_provider):
            return None
        try:
            value = self._now_ms_provider()
        except Exception:
            return None
        return int(value) if type(value) is int and value >= 0 else None

    def _age_ms(self, now_ms, enqueued_ms):
        if now_ms is None or enqueued_ms is None:
            return None
        if callable(self._elapsed_ms):
            try:
                value = self._elapsed_ms(now_ms, enqueued_ms)
            except Exception:
                return None
        else:
            value = now_ms - enqueued_ms
        return int(value) if type(value) is int and value >= 0 else None

    def take(self, now_ms=None):
        pending = self._pending
        if isinstance(pending, dict):
            if now_ms is None:
                now_ms = self._now_ms()
            age_ms = self._age_ms(now_ms, pending.get("enqueued_ms"))
            if age_ms is not None and age_ms >= self._ttl_ms:
                self._pending = None
                self.reject(pending.get("request_id"), "request_expired")
                return None
        self._pending = None
        if not isinstance(pending, dict):
            return None
        result = dict(pending)
        result.pop("enqueued_ms", None)
        return result

    def resolve(self, request_id, state, reason=None):
        if request_id != self._status.get("request_id"):
            return False
        if not isinstance(state, str) or not state:
            state = "rejected"
        status = {
            "request_id": request_id,
            "state": state,
            "reason": str(reason) if reason is not None else None,
        }
        action = self._status.get("action")
        if action is not None:
            status["action"] = action
        lesson_id = self._status.get("lesson_id")
        if lesson_id is not None:
            status["lesson_id"] = lesson_id
        self._status = status
        return True

    def reject(self, request_id, reason):
        return self.resolve(request_id, "rejected", reason)

    def applied(self, request_id, reason=None):
        return self.resolve(request_id, "applied", reason)

    def status(self):
        return dict(self._status)


class TelemetryUnavailableError(RuntimeError):
    """Safe provider error consumed by PreviewServer's 503 response path."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _member(value, name, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _nonnegative_number(value):
    return value if type(value) in (int, float) and value >= 0 else None


def _nonnegative_integer(value):
    return value if type(value) is int and value >= 0 else None


class LiveWebSidecar:
    """Own the opt-in PreviewServer, JPEG cadence, and read-only telemetry."""

    def __init__(
        self,
        state_provider,
        *,
        elapsed_ms=None,
        server_factory=PreviewServer,
        publish_interval_ms=DEFAULT_PUBLISH_INTERVAL_MS,
        frame_stale_ms=DEFAULT_FRAME_STALE_MS,
        sign_select_handler=None,
        sign_start_handler=None,
        sign_cancel_handler=None,
        sign_review_handler=None,
        sign_status_provider=None,
        sign_enabled=False,
        now_ms_provider=None,
        sign_intent_ttl_ms=2000,
    ):
        if not callable(state_provider):
            raise ValueError("state_provider must be callable")
        if type(publish_interval_ms) is not int or publish_interval_ms < 1:
            raise ValueError("publish_interval_ms must be a positive integer")
        if type(frame_stale_ms) is not int or frame_stale_ms < 1:
            raise ValueError("frame_stale_ms must be a positive integer")
        self.state_provider = state_provider
        self.elapsed_ms = elapsed_ms
        self.publish_interval_ms = publish_interval_ms
        self.frame_stale_ms = frame_stale_ms
        self.runtime = TelemetryRuntimeAdapter(elapsed_ms=elapsed_ms)
        self.web_train_intents = WebTrainIntentLatch()
        self.web_sign_intents = WebSignIntentLatch(
            now_ms_provider=now_ms_provider,
            elapsed_ms=elapsed_ms,
            ttl_ms=sign_intent_ttl_ms,
        )
        server_kwargs = dict(
            telemetry_provider=self.telemetry_json,
            train_request_handler=self.enqueue_web_train,
            train_status_provider=self.web_train_status,
        )
        # Preserve compatibility with test/dormant server factories that only
        # implement the original v1 train/telemetry arguments.  Sign routes
        # become live only when an integration supplies a sign status or
        # command handler.
        if sign_enabled or any(callable(handler) for handler in (
            sign_select_handler, sign_start_handler, sign_cancel_handler, sign_review_handler,
        )) or callable(sign_status_provider):
            server_kwargs.update({
                "sign_select_handler": sign_select_handler or self.enqueue_web_sign_select,
                "sign_start_handler": sign_start_handler or self.enqueue_web_sign_start,
                "sign_cancel_handler": sign_cancel_handler or self.enqueue_web_sign_cancel,
                "sign_review_handler": sign_review_handler or self.enqueue_web_sign_review,
                "sign_status_provider": sign_status_provider or self.sign_status,
            })
        self.server = server_factory(**server_kwargs)
        self.started = False
        self.last_offer_ms = None
        self.last_now_ms = 0
        self._now_valid = False
        self.encoding_fault = None
        self.stream_fault = None
        self.telemetry_fault = None
        self._state_fault = None
        self._state = {}

    def start(self, host="0.0.0.0", port=8080):
        """Start the read-only server, returning False instead of raising."""
        try:
            self.started = bool(self.server.start(host=host, port=port))
        except Exception as exc:
            self.started = False
            self.stream_fault = "preview_start_failed:{}".format(type(exc).__name__)
            return False
        if not self.started:
            self.stream_fault = _member(self.server, "last_fault") or "preview_start_failed"
        else:
            self.stream_fault = None
        return self.started

    def close(self):
        """Best-effort close which cannot affect the hardware main loop."""
        self.started = False
        try:
            close = getattr(self.server, "close", None)
            if callable(close):
                close()
        except Exception as exc:
            self.stream_fault = "preview_close_failed:{}".format(type(exc).__name__)

    def _elapsed(self, now_ms, previous_ms):
        now_ms = self._safe_milliseconds(now_ms)
        previous_ms = self._safe_milliseconds(previous_ms)
        if now_ms is None or previous_ms is None:
            return None
        try:
            value = (
                self.elapsed_ms(now_ms, previous_ms)
                if self.elapsed_ms is not None else now_ms - previous_ms
            )
        except Exception:
            return None
        return self._safe_milliseconds(value)

    @staticmethod
    def _safe_milliseconds(value):
        """Normalize safe Maix tick values without ever raising to main.py."""
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            result = int(value)
        elif isinstance(value, float):
            if value != value:  # NaN
                return None
            try:
                result = int(value)
            except (OverflowError, ValueError):  # +/- infinity
                return None
            if value != result:
                return None
        else:
            return None
        return result if result >= 0 else None

    def _set_now_ms(self, now_ms):
        normalized = self._safe_milliseconds(now_ms)
        self._now_valid = normalized is not None
        self.last_now_ms = normalized if normalized is not None else 0

    def _read_state(self):
        try:
            state = self.state_provider()
            if not isinstance(state, dict):
                raise ValueError("state_provider did not return a mapping")
            self._state = state
            self._state_fault = None
        except Exception as exc:
            self._state = {}
            self._state_fault = "runtime_snapshot_failed:{}".format(
                type(exc).__name__
            )

    @staticmethod
    def _training_phase(state):
        sign = _member(state, "sign_controller")
        sign_state = _member(sign, "state")
        if sign_state is None:
            sign_status = _member(state, "sign_status")
            if callable(sign_status):
                try:
                    sign_status = sign_status()
                except Exception:
                    sign_status = None
            sign_state = _member(sign_status, "state")
        sign_phases = {
            "SELECTED": "queued", "LESSON_SELECTED": "queued",
            "WAITING_CONFIRMATION": "queued", "DEMO_READY": "queued",
            "DEMO": "running", "DEMONSTRATING": "running",
            "RUNNING": "running", "ACTIVE": "running",
            "IMITATE": "running", "IMITATING": "running", "IMITATION": "running",
            "COMPLETE": "complete", "COMPLETED": "complete",
            "TIMEOUT": "timeout", "FAILED": "failed", "CANCELLED": "failed",
            "FAULT": "failed", "REVIEWED": "idle",
        }
        if sign_state in sign_phases:
            return sign_phases[sign_state]
        imitation = _member(state, "imitation_controller")
        imitation_phase = _member(imitation, "state")
        phases = {
            "IDLE": "idle", "ACTIVE": "running", "COMPLETE": "complete",
            "TIMEOUT": "timeout",
        }
        if imitation_phase in phases and imitation_phase != "IDLE":
            return phases[imitation_phase]
        train = _member(state, "train_controller")
        return {
            "REQUESTED": "requested", "QUEUED": "queued", "RUNNING": "running",
            "COMPLETED": "complete", "FAILED": "failed", "ACK_TIMEOUT": "timeout",
            "STATUS_TIMEOUT": "timeout", "BUSY": "failed", "BLOCKED": "failed",
            "REJECTED": "failed",
        }.get(_member(train, "state"), "idle")

    def _runtime_inputs(self, now_ms):
        state = self._state
        frames = _member(self.server, "frames")
        snapshot = getattr(frames, "snapshot", None)
        try:
            frame_sequence, jpeg, published_ms = snapshot() if callable(snapshot) else (0, None, None)
        except Exception:
            frame_sequence, jpeg, published_ms = 0, None, None
        age_ms = self._elapsed(now_ms, published_ms)
        available = jpeg is not None
        frame = {
            "sequence": _nonnegative_integer(frame_sequence) or 0,
            "available": available,
            "stale": (
                not self._now_valid or not available or age_ms is None
                or age_ms >= self.frame_stale_ms
            ),
            "age_ms": age_ms,
            "dropped": _nonnegative_integer(_member(frames, "dropped")) or 0,
            "encoding_fault": self.encoding_fault,
        }

        phase = _member(state, "vision_phase")
        vision_source = _member(state, "vision_source")
        ai = {}
        target = _member(state, "target_payload")
        if phase == "TARGET":
            mode = _member(state, "vision_mode")
            if isinstance(mode, str):
                ai["mode"] = mode
            model = _member(state, "vision_model")
            if isinstance(model, str) and mode == "yolo11":
                ai["model"] = model
            inference_ms = _nonnegative_number(_member(vision_source, "last_inference_ms"))
            if inference_ms is not None:
                ai["inference_ms"] = inference_ms
            inference_fps = _member(vision_source, "inference_fps")
            if callable(inference_fps):
                try:
                    inference_fps = inference_fps()
                except Exception:
                    inference_fps = None
            inference_fps = _nonnegative_number(inference_fps)
            if inference_fps is not None:
                ai["inference_fps"] = inference_fps
            objects = _member(vision_source, "last_objects")
            if isinstance(objects, (tuple, list)):
                ai["detections"] = len(objects)
            if isinstance(target, (tuple, list)) and len(target) == 6:
                label = _member(state, "target_labels", {}).get(target[0]) if isinstance(_member(state, "target_labels"), dict) else None
                confidence = _nonnegative_number(target[5])
                if isinstance(label, str):
                    ai["target"] = label
                if confidence is not None and confidence <= 100:
                    ai["confidence_pct"] = confidence

        hand = {}
        hand_source = _member(state, "hand_source")
        if phase in ("HAND", "SIGN") and hand_source is not None:
            pose = _member(hand_source, "last_posture")
            if isinstance(pose, str):
                hand["pose"] = pose
            openness = _nonnegative_number(_member(hand_source, "last_score"))
            if openness is not None and openness <= 1:
                hand["openness_pct"] = openness * 100

        imitation = _member(state, "imitation_controller")
        repetitions = _nonnegative_integer(_member(imitation, "repetitions"))
        goal = _nonnegative_integer(_member(imitation, "goal_repetitions"))
        training = {
            "phase": self._training_phase(state),
            "repetitions": repetitions or 0,
            "goal_repetitions": goal or 0,
        }
        completion = getattr(imitation, "completion_percent", None)
        try:
            completion = completion() if callable(completion) else None
        except Exception:
            completion = None
        if _nonnegative_number(completion) is not None and completion <= 100:
            training["completion_pct"] = completion
        quality_tracker = _member(imitation, "quality_tracker")
        try:
            quality = quality_tracker.summary() if quality_tracker is not None else None
        except Exception:
            quality = None
        if isinstance(quality, dict):
            quality_data = {
                "status": quality.get("quality_status"),
                "rhythm": quality.get("rhythm_status"),
                "hold": quality.get("hold_status"),
            }
            training["quality"] = {
                key: value if isinstance(value, str) else None
                for key, value in quality_data.items()
            }
            valid_pct = _nonnegative_number(quality.get("valid_frame_pct"))
            if valid_pct is not None and valid_pct <= 100:
                hand["valid_frame_pct"] = valid_pct

        return {
            "frame": frame,
            "ai": ai,
            "hand": hand,
            "training": training,
            "authority": _member(state, "authority"),
            "ack_monitor": _member(state, "ack_monitor"),
            "faults": {
                # Main has no current vision fault signal.  Do not report its
                # cumulative read-error counter as if it were a live failure.
                "vision": False,
                "jpeg": self.encoding_fault is not None,
                "stream": self.stream_fault is not None,
            },
        }

    def telemetry_json(self):
        """Return strict schema-v1 JSON for PreviewServer's GET /telemetry."""
        try:
            document = self.runtime.build(
                self.last_now_ms, **self._runtime_inputs(self.last_now_ms)
            )
        except Exception as exc:
            return self._raise_telemetry_fault("telemetry_build", exc)
        try:
            encoded = telemetry_json(document)
        except Exception as exc:
            return self._raise_telemetry_fault("telemetry_encode", exc)
        self.telemetry_fault = None
        return encoded

    # These are intentionally transport-only methods.  They do not receive or
    # reference serial/UART, controllers, frames, or any hardware API.
    def enqueue_web_train(self):
        request_id = self.web_train_intents.enqueue()
        if request_id is None:
            return None
        return {"request_id": request_id, "state": "queued_for_main"}

    def take_web_train_intent(self):
        return self.web_train_intents.take()

    def note_web_train_rejected(self, request_id, reason):
        return self.web_train_intents.reject(request_id, reason)

    def note_web_train_submitted(self, request_id):
        return self.web_train_intents.submitted(request_id)

    def set_web_train_submission_ready(self, ready):
        self.web_train_intents.set_submission_ready(bool(ready))

    def set_web_train_availability(self, can_submit, reason):
        self.web_train_intents.set_availability(can_submit, reason)

    def web_train_status(self):
        return self.web_train_intents.status()

    # Sign transport methods intentionally mirror the train methods above.
    # They do not inspect or mutate a controller and cannot emit UART data.
    def enqueue_web_sign_select(self, lesson_id):
        request_id = self.web_sign_intents.enqueue("select", lesson_id)
        if request_id is None:
            return None
        return {
            "request_id": request_id,
            "state": "queued_for_main",
            "action": "select",
        }

    def enqueue_web_sign_start(self):
        request_id = self.web_sign_intents.enqueue("start")
        if request_id is None:
            return None
        return {
            "request_id": request_id,
            "state": "queued_for_main",
            "action": "start",
        }

    def enqueue_web_sign_cancel(self):
        request_id = self.web_sign_intents.enqueue("cancel")
        if request_id is None:
            return None
        return {
            "request_id": request_id,
            "state": "queued_for_main",
            "action": "cancel",
        }

    def enqueue_web_sign_review(self, lesson_id, session_token, manual_confirm):
        request_id = self.web_sign_intents.enqueue("review", lesson_id, session_token, manual_confirm)
        if request_id is None:
            return None
        return {"request_id": request_id, "state": "queued_for_main", "action": "review"}

    def take_web_sign_intent(self):
        return self.web_sign_intents.take()

    def note_web_sign_rejected(self, request_id, reason):
        return self.web_sign_intents.reject(request_id, reason)

    def note_web_sign_applied(self, request_id, reason=None):
        return self.web_sign_intents.applied(request_id, reason)

    def sign_status(self):
        """Return a read-only, JSON-safe sign snapshot for the API page."""
        status = {}
        try:
            state = self.state_provider()
            candidate = _member(state, "sign_status")
            if callable(candidate):
                candidate = candidate()
            if isinstance(candidate, dict):
                status.update(candidate)
            sign_controller = _member(state, "sign_controller")
            controller_status = _member(sign_controller, "status")
            if callable(controller_status):
                controller_status = controller_status()
            if isinstance(controller_status, dict):
                for key, value in controller_status.items():
                    if key not in status:
                        status[key] = value
        except Exception:
            status = {}
        queue_status = self.web_sign_intents.status()
        if not status:
            status.update(queue_status)
        else:
            # Preserve the controller's actual lesson state for *all* queue
            # phases, including pending.  Queue progress is separate request
            # metadata so a browser cannot mistake an HTTP enqueue for a
            # lesson transition.
            status["request_id"] = queue_status.get("request_id", 0)
            status["request_state"] = queue_status.get("state")
            status["request_reason"] = queue_status.get("reason")
            if queue_status.get("action") is not None:
                status["action"] = queue_status.get("action")
            if queue_status.get("lesson_id") is not None:
                status.setdefault("lesson_id", queue_status.get("lesson_id"))
            if queue_status.get("reason") is not None and status.get("reason") is None:
                status["reason"] = queue_status.get("reason")
        return status

    def _raise_telemetry_fault(self, stage, exc):
        """Diagnose a provider failure once per changed code, then fail closed."""
        code = self._telemetry_fault_code(stage, exc)
        if code != self.telemetry_fault:
            # Do not print exception text: state providers may contain
            # deployment-specific paths or data.  The stable code and type are
            # enough to correlate the browser's 503 body with the device log.
            print("live web telemetry fault code={} type={}".format(
                code, type(exc).__name__
            ))
        self.telemetry_fault = code
        raise TelemetryUnavailableError(code)

    @staticmethod
    def _telemetry_fault_code(stage, exc):
        if stage != "telemetry_build" or not isinstance(exc, ValueError):
            return "{}_{}".format(stage, type(exc).__name__)
        # Only inspect known implementation messages to choose a field group;
        # neither the original message nor any field value leaves the device.
        message = str(exc)
        if message.startswith("unknown training."):
            return "telemetry_build_ValueError_training"
        if message.startswith("unknown titan.link"):
            return "telemetry_build_ValueError_link"
        groups = (
            ("elapsed_ms", "elapsed_ms"),
            ("now_ms", "now_ms"),
            ("last_rtt_ms", "rtt"),
            ("frame", "frame"),
            ("ai", "ai"),
            ("hand", "hand"),
            ("training", "training"),
            ("link", "link"),
            ("consecutive_timeouts", "link"),
            ("faults", "faults"),
            ("authority", "authority"),
            ("status_timeout", "authority"),
        )
        for marker, group in groups:
            if message.startswith(marker):
                return "telemetry_build_ValueError_{}".format(group)
        if (
            message.startswith("unsupported telemetry")
            or message.startswith("schema")
            or message.startswith("telemetry")
        ):
            return "telemetry_build_ValueError_schema"
        return "telemetry_build_ValueError_other"

    def offer(self, frame, now_ms):
        """Encode and publish an annotated frame at no more than 5 FPS."""
        self._set_now_ms(now_ms)
        self._read_state()
        if not self.started:
            return False
        if (
            self.last_offer_ms is not None
            and self._elapsed(self.last_now_ms, self.last_offer_ms) is not None
            and self._elapsed(self.last_now_ms, self.last_offer_ms) < self.publish_interval_ms
        ):
            return False
        self.last_offer_ms = self.last_now_ms
        try:
            jpeg = frame.to_jpeg().to_bytes()
            if not isinstance(jpeg, (bytes, bytearray, memoryview)):
                raise TypeError("frame.to_jpeg().to_bytes() did not return bytes")
            published = bool(self.server.publish_jpeg(bytes(jpeg), self.last_now_ms))
            self.encoding_fault = None if published else "jpeg_publish_rejected"
            return published
        except Exception as exc:
            self.encoding_fault = "jpeg_encode_failed:{}".format(type(exc).__name__)
            return False

    def poll(self, now_ms):
        """Capture a read-only state snapshot and do one bounded server poll."""
        self._set_now_ms(now_ms)
        self._read_state()
        if not self.started:
            return 0
        try:
            return self.server.poll(max_accepts=1, max_client_writes=1)
        except Exception as exc:
            self.stream_fault = "preview_poll_failed:{}".format(type(exc).__name__)
            return 0
