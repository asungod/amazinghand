"""Host-only model for the proposed HELLO-based peer session reset."""


MAX_UINT16 = 0xFFFF
MAX_UINT32 = 0xFFFFFFFF
PROPOSED_PROTOCOL_VERSION = 2
ACK_OK = 0
ACK_INVALID_PAYLOAD = 1
ACK_UNSUPPORTED = 2


def _unsigned(value, maximum, name):
    if type(value) is not int or value < 0 or value > maximum:
        raise ValueError("{} is out of range".format(name))


class PeerSessionModel:
    def __init__(self):
        self.boot_id = None
        self.last_sequence = None
        self.session_resets = 0
        self.target_clear_requests = 0

    def handle_hello(self, sequence, boot_id, version, capabilities=0):
        _unsigned(sequence, MAX_UINT16, "sequence")
        _unsigned(boot_id, MAX_UINT32, "boot_id")
        _unsigned(version, MAX_UINT32, "version")
        _unsigned(capabilities, MAX_UINT32, "capabilities")
        if version != PROPOSED_PROTOCOL_VERSION:
            return "unsupported_version", ACK_UNSUPPORTED
        if boot_id == self.boot_id:
            return "accepted_same_session", ACK_OK

        self.boot_id = boot_id
        self.last_sequence = sequence
        self.session_resets += 1
        self.target_clear_requests += 1
        return "accepted_reset", ACK_OK

    def accept_sequence(self, sequence):
        _unsigned(sequence, MAX_UINT16, "sequence")
        if self.boot_id is None:
            return "rejected_no_session"
        delta = (sequence - self.last_sequence) & MAX_UINT16
        if not 0 < delta < 0x8000:
            return "rejected_old_or_duplicate"
        self.last_sequence = sequence
        return "accepted"

    def snapshot(self):
        return {
            "boot_id": self.boot_id,
            "last_sequence": self.last_sequence,
            "session_resets": self.session_resets,
            "target_clear_requests": self.target_clear_requests,
        }


def run_vector(vector):
    model = PeerSessionModel()
    results = []
    for event in vector["events"]:
        if event["type"] == "hello":
            result, status = model.handle_hello(
                event["seq"],
                event["boot_id"],
                event["version"],
                event.get("capabilities", 0),
            )
            results.append({"result": result, "ack_status": status})
        elif event["type"] == "message":
            results.append({"result": model.accept_sequence(event["seq"])})
        else:
            raise ValueError("unknown vector event type")
    return {"results": results, "final": model.snapshot()}
