"""Host-only reference policy mapping stable VISION data to a grip intent."""


NO_ACTION = "NO_ACTION"
DEFAULT_MINIMUM_CONFIDENCE = 70
MAX_TITAN_VISION_VALUE = 0xFFFF

GRIP_POLICIES = {
    39: ("bottle", "CYLINDRICAL_GRASP"),
    41: ("cup", "POWER_GRASP"),
    65: ("remote", "PRECISION_GRASP"),
}


def _vision_payload_valid(payload):
    if not isinstance(payload, (tuple, list)) or len(payload) != 6:
        return False
    if any(type(value) is not int for value in payload):
        return False
    class_id, center_x, center_y, width, height, confidence = payload
    return (
        0 <= class_id <= MAX_TITAN_VISION_VALUE
        and 0 <= center_x <= MAX_TITAN_VISION_VALUE
        and 0 <= center_y <= MAX_TITAN_VISION_VALUE
        and 0 < width <= MAX_TITAN_VISION_VALUE
        and 0 < height <= MAX_TITAN_VISION_VALUE
        and 0 <= confidence <= 100
    )


def decide_grip(payload, minimum_confidence=DEFAULT_MINIMUM_CONFIDENCE):
    """Return a deterministic, non-actuating decision for one VISION payload."""
    if type(minimum_confidence) is not int or not 0 <= minimum_confidence <= 100:
        raise ValueError("minimum_confidence must be an integer from 0 to 100")
    if not _vision_payload_valid(payload):
        return {
            "action": NO_ACTION,
            "object": None,
            "class_id": None,
            "reason": "invalid_payload",
        }

    class_id, _, _, _, _, confidence = payload
    if confidence < minimum_confidence:
        return {
            "action": NO_ACTION,
            "object": None,
            "class_id": class_id,
            "reason": "low_confidence",
        }

    policy = GRIP_POLICIES.get(class_id)
    if policy is None:
        return {
            "action": NO_ACTION,
            "object": None,
            "class_id": class_id,
            "reason": "unsupported_class",
        }

    object_name, action = policy
    return {
        "action": action,
        "object": object_name,
        "class_id": class_id,
        "reason": "accepted",
    }


def allowed_class_ids():
    """Return the immutable class whitelist for Maix configuration."""
    return tuple(sorted(GRIP_POLICIES))

