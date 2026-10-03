"""Read-only runtime-state adapter for telemetry schema v1.

This module deliberately contains no Maix, camera, socket, or UART I/O.  It
accepts current runtime state and projects the whitelisted fields into the
strict telemetry contract.  In particular, ACK history is not treated as a
permanent online indication: current timeout/link inputs or a fresh Titan
STATUS snapshot determine link health.
"""

from telemetry_schema import build_telemetry
from status_snapshot import ACTION_NAMES, REASON_NAMES


STATUS_TIMEOUT_MS = 1500
_LINK_STATES = ("unknown", "online", "degraded", "offline")
_FRAME_KEYS = (
    "sequence", "available", "stale", "age_ms", "dropped", "encoding_fault"
)
_AI_KEYS = (
    "model", "mode", "confidence_pct", "detections", "inference_ms",
    "inference_fps", "target",
)
_HAND_KEYS = ("pose", "openness_pct", "valid_frame_pct")
_TRAINING_KEYS = (
    "phase", "repetitions", "goal_repetitions", "completion_pct", "quality"
)
_QUALITY_KEYS = ("status", "rhythm", "hold")
_CURRENT_FAULT_KEYS = ("vision", "jpeg", "stream")


def _mapping(value, name):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("{} must be an object or None".format(name))
    return value


def _select(value, name, keys):
    """Copy only known telemetry fields, so runtime internals cannot leak."""
    source = _mapping(value, name)
    return {key: source[key] for key in keys if key in source}


def _member(value, name):
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _bool(value, name):
    if type(value) is not bool:
        raise ValueError("{} must be boolean".format(name))
    return value


def _nonnegative_integer(value, name):
    if type(value) is not int or value < 0:
        raise ValueError("{} must be a non-negative integer".format(name))
    return value


def _nonnegative_milliseconds(value, name):
    """Return a canonical ``int`` for a reliable millisecond measurement.

    MaixPy tick APIs can expose integral floats or integer subclasses.  They
    are safe to normalize, while booleans, fractional values, NaN, infinities,
    and negatives must fail closed instead of reaching strict JSON telemetry.
    """
    if isinstance(value, bool):
        raise ValueError("{} must be non-negative integer milliseconds".format(name))
    if isinstance(value, int):
        result = int(value)
    elif isinstance(value, float):
        if value != value:  # NaN, without relying on optional math.isfinite.
            raise ValueError("{} must be non-negative integer milliseconds".format(name))
        try:
            result = int(value)
        except (OverflowError, ValueError):
            raise ValueError("{} must be non-negative integer milliseconds".format(name))
        if value != result:
            raise ValueError("{} must be non-negative integer milliseconds".format(name))
    else:
        raise ValueError("{} must be non-negative integer milliseconds".format(name))
    if result < 0:
        raise ValueError("{} must be non-negative integer milliseconds".format(name))
    return result


def _optional_rtt(value):
    if value is None:
        return None
    return _nonnegative_milliseconds(value, "last_rtt_ms")


def _elapsed(now_ms, previous_ms, elapsed_ms):
    if previous_ms is None:
        return None
    try:
        previous_ms = _nonnegative_milliseconds(previous_ms, "previous_ms")
    except ValueError:
        # A malformed optional timestamp is unavailable rather than a reason
        # to take the whole read-only telemetry endpoint down.
        return None
    if elapsed_ms is None:
        return _nonnegative_milliseconds(now_ms - previous_ms, "elapsed_ms")
    value = elapsed_ms(now_ms, previous_ms)
    return _nonnegative_milliseconds(value, "elapsed_ms")


def _authority_state(now_ms, authority, status_timeout_ms, elapsed_ms):
    source = _mapping(authority, "authority")
    snapshot = source.get("snapshot")
    last_status_ms = source.get("last_status_ms")
    age_ms = _elapsed(now_ms, last_status_ms, elapsed_ms)
    fresh = (
        isinstance(snapshot, dict)
        and snapshot.get("ver") is not None
        and age_ms is not None
        and 0 <= age_ms < status_timeout_ms
    )
    return snapshot if fresh else None, not fresh


def _titan_authority(snapshot):
    """Map decoded STATUS fields only; never expose the frame or raw codes."""
    if snapshot is None:
        return None, None, {"present": None, "armed": None, "fault": None}

    action = ACTION_NAMES.get(snapshot.get("action"))
    reason = REASON_NAMES.get(snapshot.get("reason"))
    if (
        snapshot.get("gate_present") is not True
        or type(snapshot.get("gate_armed")) is not bool
        or type(snapshot.get("gate_fault")) is not bool
    ):
        gate = {"present": None, "armed": None, "fault": None}
    else:
        gate = {
            "present": True,
            "armed": snapshot["gate_armed"],
            "fault": snapshot["gate_fault"],
        }
    return action, reason, gate


def _titan_vision_stale(snapshot):
    """Use only fresh Titan STATUS candidate freshness for health.vision."""
    if snapshot is None or snapshot.get("have_vision") is not True:
        return True
    vision_stale = snapshot.get("vision_stale")
    return vision_stale if type(vision_stale) is bool else True


def _current_link(ack_monitor, link, snapshot):
    source = _mapping(link, "link")
    requested_state = source.get("state")
    if requested_state is not None and requested_state not in _LINK_STATES:
        raise ValueError("link.state is invalid")

    explicit_fault = source.get("fault", False)
    _bool(explicit_fault, "link.fault")
    timeout_count = source.get("consecutive_timeouts")
    if timeout_count is None:
        timeout_count = _member(ack_monitor, "consecutive_timeouts")
    if timeout_count is None:
        timeout_count = 0
    _nonnegative_integer(timeout_count, "consecutive_timeouts")

    if requested_state is None:
        if explicit_fault or timeout_count > 0:
            state = "degraded"
        elif snapshot is None or snapshot.get("link_online") is None:
            state = "unknown"
        elif snapshot.get("link_online") is True:
            state = "online"
        else:
            state = "offline"
    else:
        state = requested_state

    # An explicit current failure always wins; completed historical ACKs do not.
    if explicit_fault or timeout_count > 0:
        state = "degraded"
    uart_fault = explicit_fault or timeout_count > 0 or state in ("degraded", "offline")

    rtt_ms = _member(ack_monitor, "last_rtt_ms")
    if rtt_ms is None and "last_rtt_ms" in source:
        rtt_ms = source["last_rtt_ms"]
    return state, _optional_rtt(rtt_ms), uart_fault


def _current_faults(faults):
    source = _mapping(faults, "faults")
    result = {}
    for key in _CURRENT_FAULT_KEYS:
        if key in source:
            result[key] = _bool(source[key], "faults." + key)
        else:
            result[key] = False
    return result


def _normalize_optional_milliseconds(data, key, name):
    if key in data and data[key] is not None:
        data[key] = _nonnegative_milliseconds(data[key], name)


def build_runtime_telemetry(
    now_ms,
    *,
    frame=None,
    ai=None,
    hand=None,
    training=None,
    vision=None,
    authority=None,
    ack_monitor=None,
    link=None,
    faults=None,
    status_timeout_ms=STATUS_TIMEOUT_MS,
    elapsed_ms=None
):
    """Build a strict v1 document from a read-only MaixCAM2 runtime snapshot.

    ``authority`` is main.py's ``{"snapshot", "last_status_ms"}`` mapping.
    ``ack_monitor.last_rtt_ms`` is emitted as ``titan.rtt_ms`` and is UART RTT.
    ``link`` accepts current-only ``state``, ``fault``,
    ``consecutive_timeouts``, and (when no monitor is supplied) ``last_rtt_ms``.
    ``faults`` accepts only current boolean ``vision``, ``jpeg``, and ``stream``;
    UART fault is derived from the current link state instead of cumulative
    monitor counters.  ``elapsed_ms`` may supply Maix tick-wrap arithmetic.
    """
    now_ms = _nonnegative_milliseconds(now_ms, "now_ms")
    status_timeout_ms = _nonnegative_milliseconds(
        status_timeout_ms, "status_timeout_ms"
    )
    if status_timeout_ms == 0:
        raise ValueError("status_timeout_ms must be positive")

    frame_data = _select(frame, "frame", _FRAME_KEYS)
    ai_data = _select(ai, "ai", _AI_KEYS)
    hand_data = _select(hand, "hand", _HAND_KEYS)
    training_data = _select(training, "training", _TRAINING_KEYS)
    if "quality" in training_data:
        training_data["quality"] = _select(
            training_data["quality"], "training.quality", _QUALITY_KEYS
        )
    _normalize_optional_milliseconds(frame_data, "age_ms", "frame.age_ms")
    _normalize_optional_milliseconds(ai_data, "inference_ms", "ai.inference_ms")

    frame_stale = frame_data.get("stale", True)
    _bool(frame_stale, "frame.stale")

    snapshot, titan_status_stale = _authority_state(
        now_ms, authority, status_timeout_ms, elapsed_ms
    )
    action, reason, gate = _titan_authority(snapshot)
    vision_stale = _titan_vision_stale(snapshot)
    link_state, rtt_ms, uart_fault = _current_link(ack_monitor, link, snapshot)
    current_faults = _current_faults(faults)

    return build_telemetry(
        now_ms,
        frame=frame_data,
        ai=ai_data,
        hand=hand_data,
        training=training_data,
        titan={
            "link": link_state,
            "rtt_ms": rtt_ms,
            "action": action,
            "reason": reason,
            "gate": gate,
        },
        stale={
            "frame": frame_stale,
            "vision": vision_stale,
            "titan_status": titan_status_stale,
        },
        faults={
            "vision": current_faults["vision"],
            "uart": uart_fault,
            "jpeg": current_faults["jpeg"],
            "stream": current_faults["stream"],
        },
    )


class TelemetryRuntimeAdapter:
    """Small callable wrapper for a sidecar that owns shared runtime state."""

    def __init__(self, status_timeout_ms=STATUS_TIMEOUT_MS, elapsed_ms=None):
        status_timeout_ms = _nonnegative_milliseconds(
            status_timeout_ms, "status_timeout_ms"
        )
        if status_timeout_ms == 0:
            raise ValueError("status_timeout_ms must be positive")
        self.status_timeout_ms = status_timeout_ms
        self.elapsed_ms = elapsed_ms

    def build(self, now_ms, **runtime_state):
        """Delegate to :func:`build_runtime_telemetry` without retaining state."""
        if "status_timeout_ms" in runtime_state or "elapsed_ms" in runtime_state:
            raise ValueError("adapter timing parameters are fixed at construction")
        return build_runtime_telemetry(
            now_ms,
            status_timeout_ms=self.status_timeout_ms,
            elapsed_ms=self.elapsed_ms,
            **runtime_state
        )
