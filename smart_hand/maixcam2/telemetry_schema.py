"""Strict versioned, hardware-free telemetry contract for the web preview."""

try:
    import json
except ImportError:  # pragma: no cover - constrained runtime fallback
    json = None


TELEMETRY_SCHEMA_NAME = "amazinghand.maixcam2.telemetry"
TELEMETRY_SCHEMA_VERSION = 1
_LINK_STATES = ("unknown", "online", "degraded", "offline")
_TRAINING_PHASES = ("idle", "requested", "queued", "running", "complete", "failed", "timeout")
_ROOT_KEYS = ("schema", "schema_version", "timestamp_ms", "frame", "ai", "hand", "training", "titan", "health")
_FRAME_KEYS = ("sequence", "available", "stale", "age_ms", "dropped", "encoding_fault")
_AI_KEYS = ("model", "mode", "confidence_pct", "detections", "inference_ms", "inference_fps", "target")
_HAND_KEYS = ("pose", "openness_pct", "valid_frame_pct")
_TRAINING_KEYS = ("phase", "repetitions", "goal_repetitions", "completion_pct", "quality")
_QUALITY_KEYS = ("status", "rhythm", "hold")
_TITAN_KEYS = ("link", "rtt_ms", "action", "reason", "gate")
_GATE_KEYS = ("present", "armed", "fault")
_HEALTH_KEYS = ("stale", "faults")
_STALE_KEYS = ("frame", "vision", "titan_status")
_FAULT_KEYS = ("vision", "uart", "jpeg", "stream")


def _mapping(value, name):
    if not isinstance(value, dict):
        raise ValueError("{} must be an object".format(name))
    return value


def _exact_keys(value, name, expected):
    mapping = _mapping(value, name)
    if set(mapping) != set(expected):
        raise ValueError("{} has unexpected or missing keys".format(name))
    return mapping


def _input(value, name, allowed):
    if value is None:
        return {}
    mapping = _mapping(value, name)
    unknown = set(mapping) - set(allowed)
    if unknown:
        raise ValueError("{} has unknown keys: {}".format(name, sorted(unknown)))
    return mapping


def _merge(defaults, override, name, allowed):
    result = dict(defaults)
    result.update(_input(override, name, allowed))
    return result


def _integer(value, name, minimum=None):
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ValueError("{} must be an integer".format(name))
    return value


def _optional_integer(value, name, minimum=None):
    return None if value is None else _integer(value, name, minimum)


def _optional_number(value, name, minimum=None, maximum=None):
    if value is None:
        return None
    if type(value) not in (int, float):
        raise ValueError("{} must be a number or None".format(name))
    if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        raise ValueError("{} is outside its allowed range".format(name))
    return value


def _optional_text(value, name):
    if value is not None and not isinstance(value, str):
        raise ValueError("{} must be text or None".format(name))
    return value


def _bool(value, name):
    if type(value) is not bool:
        raise ValueError("{} must be boolean".format(name))
    return value


def build_telemetry(now_ms, *, frame=None, ai=None, hand=None, training=None, titan=None, stale=None, faults=None):
    """Build the complete whitelist-only schema-v1 document.

    Values are optional only where ``None`` explicitly represents unavailable
    telemetry; unknown keys are rejected rather than serialized.
    """
    frame_data = _merge({"sequence": 0, "available": False, "stale": True, "age_ms": None, "dropped": 0, "encoding_fault": None}, frame, "frame", _FRAME_KEYS)
    ai_data = _merge({"model": None, "mode": None, "confidence_pct": None, "detections": None, "inference_ms": None, "inference_fps": None, "target": None}, ai, "ai", _AI_KEYS)
    hand_data = _merge({"pose": None, "openness_pct": None, "valid_frame_pct": None}, hand, "hand", _HAND_KEYS)
    training_data = _merge({"phase": "idle", "repetitions": 0, "goal_repetitions": 0, "completion_pct": None, "quality": {"status": None, "rhythm": None, "hold": None}}, training, "training", _TRAINING_KEYS)
    training_data["quality"] = _merge({"status": None, "rhythm": None, "hold": None}, training_data["quality"], "training.quality", _QUALITY_KEYS)
    titan_data = _merge({"link": "unknown", "rtt_ms": None, "action": None, "reason": None, "gate": {"present": None, "armed": None, "fault": None}}, titan, "titan", _TITAN_KEYS)
    titan_data["gate"] = _merge({"present": None, "armed": None, "fault": None}, titan_data["gate"], "titan.gate", _GATE_KEYS)
    stale_data = _merge({"frame": True, "vision": True, "titan_status": True}, stale, "stale", _STALE_KEYS)
    fault_data = _merge({"vision": False, "uart": False, "jpeg": False, "stream": False}, faults, "faults", _FAULT_KEYS)
    document = {
        "schema": TELEMETRY_SCHEMA_NAME,
        "schema_version": TELEMETRY_SCHEMA_VERSION,
        "timestamp_ms": _integer(now_ms, "now_ms", 0),
        "frame": frame_data, "ai": ai_data, "hand": hand_data,
        "training": training_data, "titan": titan_data,
        "health": {"stale": stale_data, "faults": fault_data},
    }
    validate_telemetry(document)
    return document


def validate_telemetry(document):
    """Validate and return an exact schema-v1 document; reject extras."""
    root = _exact_keys(document, "telemetry", _ROOT_KEYS)
    if root["schema"] != TELEMETRY_SCHEMA_NAME or root["schema_version"] != TELEMETRY_SCHEMA_VERSION:
        raise ValueError("unsupported telemetry schema or version")
    _integer(root["timestamp_ms"], "timestamp_ms", 0)

    frame = _exact_keys(root["frame"], "frame", _FRAME_KEYS)
    _integer(frame["sequence"], "frame.sequence", 0)
    _bool(frame["available"], "frame.available")
    _bool(frame["stale"], "frame.stale")
    _optional_number(frame["age_ms"], "frame.age_ms", 0)
    _integer(frame["dropped"], "frame.dropped", 0)
    _optional_text(frame["encoding_fault"], "frame.encoding_fault")

    ai = _exact_keys(root["ai"], "ai", _AI_KEYS)
    _optional_text(ai["model"], "ai.model")
    _optional_text(ai["mode"], "ai.mode")
    _optional_number(ai["confidence_pct"], "ai.confidence_pct", 0, 100)
    _optional_integer(ai["detections"], "ai.detections", 0)
    _optional_number(ai["inference_ms"], "ai.inference_ms", 0)
    _optional_number(ai["inference_fps"], "ai.inference_fps", 0)
    _optional_text(ai["target"], "ai.target")

    hand = _exact_keys(root["hand"], "hand", _HAND_KEYS)
    _optional_text(hand["pose"], "hand.pose")
    _optional_number(hand["openness_pct"], "hand.openness_pct", 0, 100)
    _optional_number(hand["valid_frame_pct"], "hand.valid_frame_pct", 0, 100)

    training = _exact_keys(root["training"], "training", _TRAINING_KEYS)
    if training["phase"] not in _TRAINING_PHASES:
        raise ValueError("unknown training.phase")
    _integer(training["repetitions"], "training.repetitions", 0)
    _integer(training["goal_repetitions"], "training.goal_repetitions", 0)
    _optional_number(training["completion_pct"], "training.completion_pct", 0, 100)
    quality = _exact_keys(training["quality"], "training.quality", _QUALITY_KEYS)
    for key in _QUALITY_KEYS:
        _optional_text(quality[key], "training.quality." + key)

    titan = _exact_keys(root["titan"], "titan", _TITAN_KEYS)
    if titan["link"] not in _LINK_STATES:
        raise ValueError("unknown titan.link")
    _optional_number(titan["rtt_ms"], "titan.rtt_ms", 0)
    _optional_text(titan["action"], "titan.action")
    _optional_text(titan["reason"], "titan.reason")
    gate = _exact_keys(titan["gate"], "titan.gate", _GATE_KEYS)
    for key in _GATE_KEYS:
        if gate[key] is not None:
            _bool(gate[key], "titan.gate." + key)

    health = _exact_keys(root["health"], "health", _HEALTH_KEYS)
    for section_name, expected in (("stale", _STALE_KEYS), ("faults", _FAULT_KEYS)):
        section = _exact_keys(health[section_name], "health." + section_name, expected)
        for key, value in section.items():
            _bool(value, "health.{}.{}".format(section_name, key))
    return document


def telemetry_json(document):
    """Return compact UTF-8 JSON after validation, without starting I/O.

    MaixPy builds may expose a reduced JSON module which accepts ``dumps`` but
    not CPython's optional keyword arguments.  Validation happens before all
    encoder attempts, so compatibility fallback cannot relax the wire schema.
    """
    validate_telemetry(document)
    if json is None:
        raise RuntimeError("JSON support unavailable in this runtime")
    try:
        encoded = json.dumps(document, separators=(",", ":"), sort_keys=True)
    except TypeError:
        try:
            # Some embedded implementations support compact separators but do
            # not implement deterministic key ordering.
            encoded = json.dumps(document, separators=(",", ":"))
        except TypeError:
            # Minimal MaixPy/ujson-compatible invocation.  These encoders use
            # their compact default representation; output remains UTF-8 bytes.
            encoded = json.dumps(document)
    if isinstance(encoded, bytes):
        return bytes(encoded)
    if not isinstance(encoded, str):
        raise TypeError("json.dumps did not return text or bytes")
    return encoded.encode("utf-8")
