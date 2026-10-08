"""Maix-side decoder for Titan outbound STATUS v1 (exactly 8 args).

Does not change PING/VISION/ACK framing. STATUS must never close a pending
PING/VISION ACK. hardware_accessed is not required to import this module.
"""

STATUS_VERSION = 1
STATUS_ARG_COUNT = 8

FLAG_LINK_ONLINE = 1 << 0
FLAG_HAVE_VISION = 1 << 1
FLAG_VISION_STALE = 1 << 2
FLAG_HAVE_LAST_RX = 1 << 3
FLAG_GATE_PRESENT = 1 << 4
FLAG_GATE_ARMED = 1 << 5
FLAG_GATE_FAULT = 1 << 6
FLAG_HAVE_ACTIONABLE = 1 << 7

ACTION_NONE = 0
ACTION_CYLINDRICAL = 1
ACTION_POWER = 2
ACTION_PRECISION = 3

REASON_ACCEPTED = 0
REASON_INVALID_PAYLOAD = 1
REASON_INVALID_CONFIGURATION = 2
REASON_LOW_CONFIDENCE = 3
REASON_UNSUPPORTED_CLASS = 4

POSE_OK = 0
POSE_NO_ACTION = 1
POSE_NOT_CONFIGURED = 2
POSE_INVALID_PROFILE = 3

SUBMIT_UNKNOWN = 0
SUBMIT_NOT_CONFIGURED = 1
SUBMIT_BLOCKED = 2
SUBMIT_SUBMITTED = 3

FAULT_NONE = 0
FAULT_UNKNOWN = 255

ACTION_NAMES = {
    ACTION_NONE: "NONE",
    ACTION_CYLINDRICAL: "CYLINDRICAL",
    ACTION_POWER: "POWER",
    ACTION_PRECISION: "PRECISION",
}
REASON_NAMES = {
    REASON_ACCEPTED: "accepted",
    REASON_INVALID_PAYLOAD: "invalid_payload",
    REASON_INVALID_CONFIGURATION: "invalid_configuration",
    REASON_LOW_CONFIDENCE: "low_confidence",
    REASON_UNSUPPORTED_CLASS: "unsupported_class",
}
POSE_NAMES = {
    POSE_OK: "OK",
    POSE_NO_ACTION: "NO_ACTION",
    POSE_NOT_CONFIGURED: "NOT_CONFIGURED",
    POSE_INVALID_PROFILE: "INVALID_PROFILE",
}
SUBMIT_NAMES = {
    SUBMIT_UNKNOWN: "UNKNOWN",
    SUBMIT_NOT_CONFIGURED: "NOT_CONFIGURED",
    SUBMIT_BLOCKED: "BLOCKED",
    SUBMIT_SUBMITTED: "SUBMITTED",
}

UNKNOWN_SNAPSHOT = {
    "ver": None,
    "flags": 0,
    "link_online": None,
    "have_vision": None,
    "vision_stale": None,
    "have_last_rx": False,
    "gate_present": None,
    "gate_armed": None,
    "gate_fault": None,
    "have_actionable": None,
    "last_rx_seq": None,
    "action": None,
    "reason": None,
    "pose": None,
    "submit": SUBMIT_UNKNOWN,
    "fault": FAULT_UNKNOWN,
    "tx_seq": None,
}


def derive_submit(pose, gate_present, gate_blocked, write_observed_ok, write_path_present=False):
    if pose in (POSE_NOT_CONFIGURED, POSE_INVALID_PROFILE):
        return SUBMIT_NOT_CONFIGURED
    if not write_path_present or not gate_present:
        return SUBMIT_UNKNOWN
    if gate_blocked:
        return SUBMIT_BLOCKED
    if write_observed_ok:
        return SUBMIT_SUBMITTED
    return SUBMIT_UNKNOWN


def pack_flags(
    *,
    link_online,
    have_vision,
    vision_stale,
    have_last_rx,
    gate_present=False,
    gate_armed=False,
    gate_fault=False,
    have_actionable=False,
):
    flags = 0
    if link_online:
        flags |= FLAG_LINK_ONLINE
    if have_vision:
        flags |= FLAG_HAVE_VISION
    if vision_stale:
        flags |= FLAG_VISION_STALE
    if have_last_rx:
        flags |= FLAG_HAVE_LAST_RX
    if gate_present:
        flags |= FLAG_GATE_PRESENT
        if gate_armed:
            flags |= FLAG_GATE_ARMED
        if gate_fault:
            flags |= FLAG_GATE_FAULT
    if have_actionable:
        flags |= FLAG_HAVE_ACTIONABLE
    return flags


def interpret_status(message):
    if not isinstance(message, dict) or message.get("type") != "STATUS":
        raise ValueError("not a STATUS frame")
    args = message.get("args")
    if not isinstance(args, list) or len(args) != STATUS_ARG_COUNT:
        raise ValueError("STATUS argument count must be 8")
    ver, flags, last_rx_seq, action, reason, pose, submit, fault = args
    if ver != STATUS_VERSION:
        raise ValueError("unsupported STATUS version")
    if flags > 0xFFFF:
        raise ValueError("flags out of range")
    if last_rx_seq > 0xFFFF:
        raise ValueError("last_rx_seq out of range")
    if action not in ACTION_NAMES:
        raise ValueError("action out of range")
    if reason not in REASON_NAMES:
        raise ValueError("reason out of range")
    if pose not in POSE_NAMES:
        raise ValueError("pose out of range")
    if submit not in SUBMIT_NAMES:
        raise ValueError("submit out of range")
    if fault != FAULT_UNKNOWN and not 0 <= fault <= 12:
        raise ValueError("fault out of range")
    if not (flags & FLAG_GATE_PRESENT) and submit == SUBMIT_SUBMITTED:
        raise ValueError("SUBMITTED is illegal without a servo write path")
    if pose in (POSE_NOT_CONFIGURED, POSE_INVALID_PROFILE):
        if submit != SUBMIT_NOT_CONFIGURED:
            raise ValueError("unconfigured pose must report submit=NOT_CONFIGURED")
        if flags & FLAG_HAVE_ACTIONABLE:
            raise ValueError("unconfigured pose cannot be actionable")

    gate_present = bool(flags & FLAG_GATE_PRESENT)
    return {
        "ver": ver,
        "flags": flags,
        "link_online": bool(flags & FLAG_LINK_ONLINE),
        "have_vision": bool(flags & FLAG_HAVE_VISION),
        "vision_stale": bool(flags & FLAG_VISION_STALE),
        "have_last_rx": bool(flags & FLAG_HAVE_LAST_RX),
        "gate_present": gate_present,
        "gate_armed": None if not gate_present else bool(flags & FLAG_GATE_ARMED),
        "gate_fault": None if not gate_present else bool(flags & FLAG_GATE_FAULT),
        "have_actionable": bool(flags & FLAG_HAVE_ACTIONABLE),
        "last_rx_seq": last_rx_seq if flags & FLAG_HAVE_LAST_RX else None,
        "action": action,
        "reason": reason,
        "pose": pose,
        "submit": submit,
        "fault": fault if gate_present else FAULT_UNKNOWN,
        "tx_seq": message.get("seq"),
    }


def authority_status_line(snapshot):
    if snapshot is None or snapshot.get("ver") is None:
        return "AUTH UNKNOWN"
    gate = "UNKNOWN"
    if snapshot["gate_present"]:
        if snapshot["gate_fault"]:
            gate = "FAULT"
        elif snapshot["gate_armed"]:
            gate = "ARMED"
        else:
            gate = "DISARMED"
    return "AUTH link={} vis={} stale={} act={} reason={} pose={} submit={} gate={}".format(
        "ON" if snapshot["link_online"] else "OFF",
        "ON" if snapshot["have_vision"] else "OFF",
        1 if snapshot["vision_stale"] else 0,
        ACTION_NAMES.get(snapshot["action"], "?"),
        REASON_NAMES.get(snapshot["reason"], "?"),
        POSE_NAMES.get(snapshot["pose"], "?"),
        SUBMIT_NAMES.get(snapshot["submit"], "?"),
        gate,
    )


def authority_display_line(snapshot):
    """Compact physical-display line; full detail remains in console logs."""
    if snapshot is None or snapshot.get("ver") is None:
        return "AUTH UNKNOWN"
    action = {
        ACTION_NONE: "NONE",
        ACTION_CYLINDRICAL: "CYL",
        ACTION_POWER: "PWR",
        ACTION_PRECISION: "PREC",
    }.get(snapshot.get("action"), "?")
    if not snapshot.get("gate_present"):
        gate = "UNK"
    elif snapshot.get("gate_fault"):
        gate = "FAULT"
    else:
        gate = "OK"
    return "AUTH L={} V={} S={} A={} P={} G={}".format(
        "ON" if snapshot.get("link_online") else "OFF",
        "ON" if snapshot.get("have_vision") else "OFF",
        1 if snapshot.get("vision_stale") else 0,
        action,
        POSE_NAMES.get(snapshot.get("pose"), "?"),
        gate,
    )


AITRUST_VERSION = 1
AITRUST_ARG_COUNT = 4
AITRUST_TIMEOUT_MS = 1500

AITRUST_CLASS_TRUSTED = 0
AITRUST_CLASS_UNCERTAIN = 1
AITRUST_CLASS_ANOMALOUS = 2

AITRUST_CLASS_NAMES = {
    AITRUST_CLASS_TRUSTED: "TRUSTED",
    AITRUST_CLASS_UNCERTAIN: "UNCERTAIN",
    AITRUST_CLASS_ANOMALOUS: "ANOMALOUS",
}

UNKNOWN_AITRUST_SNAPSHOT = {
    "version": None,
    "ready": None,
    "class_id": None,
    "vision_age_ms": None,
    "seq": None,
}


def interpret_aitrust(message):
    """Decode and validate inbound Titan AITRUST telemetry.

    Parameters must be 4 uint32: version=1, ready (0/1), class_id (0/1/2),
    vision_age_ms (0..0xFFFFFFFF).  Returns dict with ready explicitly converted
    to boolean.  Raises ValueError for any malformed or out-of-range field.
    """
    if not isinstance(message, dict) or message.get("type") != "AITRUST":
        raise ValueError("not an AITRUST frame")
    args = message.get("args")
    if not isinstance(args, list) or len(args) != AITRUST_ARG_COUNT:
        raise ValueError("AITRUST argument count must be 4")
    ver, ready, class_id, vision_age_ms = args
    if ver != AITRUST_VERSION:
        raise ValueError("unsupported AITRUST version")
    if ready not in (0, 1):
        raise ValueError("ready out of range")
    if class_id not in AITRUST_CLASS_NAMES:
        raise ValueError("class_id out of range")
    if not (0 <= vision_age_ms <= 0xFFFFFFFF):
        raise ValueError("vision_age_ms out of range")
    return {
        "version": ver,
        "ready": bool(ready == 1),
        "class_id": class_id,
        "vision_age_ms": vision_age_ms,
        "seq": message.get("seq"),
    }


def aitrust_status_line(snapshot):
    if snapshot is None or snapshot.get("version") is None:
        return "AITRUST UNKNOWN"
    return "AITRUST v={} ready={} class={} age_ms={}".format(
        snapshot["version"],
        1 if snapshot["ready"] else 0,
        AITRUST_CLASS_NAMES.get(snapshot["class_id"], "?"),
        snapshot["vision_age_ms"],
    )
