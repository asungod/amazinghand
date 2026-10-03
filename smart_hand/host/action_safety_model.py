"""Host-only reference model for future Titan motion authorization."""


MAX_SEQUENCE = 0xFFFF


class MotionSafetyGate:
    def __init__(self, target_timeout_ms):
        if target_timeout_ms <= 0:
            raise ValueError("target_timeout_ms must be positive")
        self.target_timeout_ms = target_timeout_ms
        self.link_online = False
        self.armed = False
        self.fault_latched = False
        self.target_sequence = None
        self.target_seen_ms = None
        self.motion_active = False
        self.safe_stop_requests = 0
        self.last_block_reason = "link_offline"

    def _clear_target(self):
        self.target_sequence = None
        self.target_seen_ms = None

    def _request_safe_stop(self, reason):
        self.last_block_reason = reason
        if not self.motion_active:
            return None
        self.motion_active = False
        self.safe_stop_requests += 1
        return "safe_stop_required"

    def set_link(self, online):
        if type(online) is not bool:
            raise ValueError("online must be a boolean")
        self.link_online = online
        if online:
            return None
        self.armed = False
        self._clear_target()
        return self._request_safe_stop("link_offline")

    def arm(self):
        if self.fault_latched:
            self.last_block_reason = "fault_latched"
            return False
        if not self.link_online:
            self.last_block_reason = "link_offline"
            return False
        self.armed = True
        self.last_block_reason = "target_missing"
        return True

    def disarm(self):
        self.armed = False
        self._clear_target()
        return self._request_safe_stop("disarmed")

    def _sequence_is_newer(self, sequence):
        if type(sequence) is not int or sequence < 0 or sequence > MAX_SEQUENCE:
            raise ValueError("sequence must be an unsigned 16-bit integer")
        if self.target_sequence is None:
            return True
        delta = (sequence - self.target_sequence) & MAX_SEQUENCE
        return 0 < delta < 0x8000

    def note_target(self, sequence, now_ms):
        if not self.link_online:
            self.last_block_reason = "link_offline"
            return False
        if not self._sequence_is_newer(sequence):
            return False
        self.target_sequence = sequence
        self.target_seen_ms = now_ms
        return True

    def target_is_fresh(self, now_ms, elapsed_ms):
        return (
            self.target_seen_ms is not None
            and 0 <= elapsed_ms(now_ms, self.target_seen_ms) <= self.target_timeout_ms
        )

    def can_start_motion(self, now_ms, elapsed_ms):
        if self.fault_latched:
            self.last_block_reason = "fault_latched"
        elif not self.link_online:
            self.last_block_reason = "link_offline"
        elif not self.armed:
            self.last_block_reason = "disarmed"
        elif self.motion_active:
            self.last_block_reason = "motion_active"
        elif self.target_seen_ms is None:
            self.last_block_reason = "target_missing"
        elif not self.target_is_fresh(now_ms, elapsed_ms):
            self.last_block_reason = "target_stale"
        else:
            self.last_block_reason = "none"
            return True
        return False

    def start_motion(self, now_ms, elapsed_ms):
        if not self.can_start_motion(now_ms, elapsed_ms):
            return False
        self.motion_active = True
        return True

    def complete_motion(self):
        self.motion_active = False

    def tick(self, now_ms, elapsed_ms):
        if not self.motion_active:
            return None
        if not self.target_is_fresh(now_ms, elapsed_ms):
            self._clear_target()
            return self._request_safe_stop("target_stale")
        return None

    def latch_fault(self):
        self.fault_latched = True
        self.armed = False
        self._clear_target()
        return self._request_safe_stop("fault_latched")

    def clear_fault(self):
        if self.motion_active or self.armed:
            return False
        self.fault_latched = False
        self.last_block_reason = "disarmed" if self.link_online else "link_offline"
        return True

    def summary(self):
        return (
            "link_online={} armed={} fault_latched={} target_seq={} "
            "motion_active={} safe_stop_requests={} block_reason={}".format(
                int(self.link_online),
                int(self.armed),
                int(self.fault_latched),
                self.target_sequence if self.target_sequence is not None else -1,
                int(self.motion_active),
                self.safe_stop_requests,
                self.last_block_reason,
            )
        )
