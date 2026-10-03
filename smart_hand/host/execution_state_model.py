"""Host-only reference state machine for future Titan grasp execution.

This module never talks to a servo.  It defines the event ordering and safety
invariants that a later RT-Thread implementation must preserve.
"""


DISARMED = "DISARMED"
READY = "READY"
CLOSING = "CLOSING"
HOLDING = "HOLDING"
RELEASING = "RELEASING"
FAULT = "FAULT"

ACTIVE_STATES = (CLOSING, HOLDING, RELEASING)
MAX_SEQUENCE = 0xFFFF


class ExecutionStateMachine:
    def __init__(self, target_timeout_ms=750, closing_timeout_ms=3000,
                 releasing_timeout_ms=3000):
        for name, value in (
            ("target_timeout_ms", target_timeout_ms),
            ("closing_timeout_ms", closing_timeout_ms),
            ("releasing_timeout_ms", releasing_timeout_ms),
        ):
            if type(value) is not int or value <= 0:
                raise ValueError("{} must be a positive integer".format(name))

        self.target_timeout_ms = target_timeout_ms
        self.closing_timeout_ms = closing_timeout_ms
        self.releasing_timeout_ms = releasing_timeout_ms
        self.state = DISARMED
        self.link_online = False
        self.armed = False
        self.target_sequence = None
        self.target_seen_ms = None
        self.grip_intent = None
        self.state_entered_ms = 0
        self.fault_reason = None
        self.safe_stop_required = False
        self.event_count = 0

    @staticmethod
    def _elapsed(now_ms, previous_ms, elapsed_ms):
        value = elapsed_ms(now_ms, previous_ms)
        if value < 0:
            raise ValueError("elapsed time must not be negative")
        return value

    def _clear_target(self):
        self.target_sequence = None
        self.target_seen_ms = None
        self.grip_intent = None

    def _enter(self, state, now_ms):
        self.state = state
        self.state_entered_ms = now_ms
        self.event_count += 1

    def _latch_fault(self, reason, now_ms):
        was_active = self.state in ACTIVE_STATES
        self.armed = False
        self._clear_target()
        self.fault_reason = reason
        self.safe_stop_required = self.safe_stop_required or was_active
        self._enter(FAULT, now_ms)
        return "safe_stop_required" if was_active else "fault_latched"

    def set_link(self, online, now_ms=0):
        if type(online) is not bool:
            raise ValueError("online must be a boolean")
        self.link_online = online
        if online:
            return None
        if self.state in ACTIVE_STATES:
            return self._latch_fault("link_offline", now_ms)
        self.armed = False
        self._clear_target()
        if self.state != FAULT:
            self._enter(DISARMED, now_ms)
        return None

    def arm(self, now_ms=0):
        if self.state == FAULT or not self.link_online:
            return False
        self.armed = True
        self.safe_stop_required = False
        self._enter(READY, now_ms)
        return True

    def disarm(self, now_ms=0):
        was_active = self.state in ACTIVE_STATES
        self.armed = False
        self._clear_target()
        self.safe_stop_required = self.safe_stop_required or was_active
        self._enter(DISARMED, now_ms)
        return "safe_stop_required" if was_active else None

    def _sequence_is_newer(self, sequence):
        if type(sequence) is not int or not 0 <= sequence <= MAX_SEQUENCE:
            raise ValueError("sequence must be an unsigned 16-bit integer")
        if self.target_sequence is None:
            return True
        delta = (sequence - self.target_sequence) & MAX_SEQUENCE
        return 0 < delta < 0x8000

    def note_target(self, sequence, grip_intent, now_ms):
        if not self.link_online or self.state == FAULT:
            return False
        if not isinstance(grip_intent, str) or not grip_intent or grip_intent == "NO_ACTION":
            return False
        if not self._sequence_is_newer(sequence):
            return False
        self.target_sequence = sequence
        self.target_seen_ms = now_ms
        self.grip_intent = grip_intent
        return True

    def target_is_fresh(self, now_ms, elapsed_ms):
        return (
            self.target_seen_ms is not None
            and self._elapsed(now_ms, self.target_seen_ms, elapsed_ms)
            <= self.target_timeout_ms
        )

    def request_grasp(self, now_ms, elapsed_ms):
        if self.state != READY or not self.armed or not self.link_online:
            return False
        if not self.target_is_fresh(now_ms, elapsed_ms):
            return False
        self._enter(CLOSING, now_ms)
        return True

    def note_contact_stable(self, now_ms):
        if self.state != CLOSING:
            return False
        self._enter(HOLDING, now_ms)
        return True

    def request_release(self, now_ms):
        if self.state not in (CLOSING, HOLDING):
            return False
        self._enter(RELEASING, now_ms)
        return True

    def complete_release(self, now_ms):
        if self.state != RELEASING:
            return False
        self._clear_target()
        self._enter(READY if self.armed and self.link_online else DISARMED, now_ms)
        return True

    def latch_fault(self, reason, now_ms):
        if not isinstance(reason, str) or not reason:
            raise ValueError("fault reason must be a non-empty string")
        return self._latch_fault(reason, now_ms)

    def clear_fault(self, now_ms=0):
        if self.state != FAULT:
            return False
        self.fault_reason = None
        self.safe_stop_required = False
        self.armed = False
        self._clear_target()
        self._enter(DISARMED, now_ms)
        return True

    def tick(self, now_ms, elapsed_ms):
        if self.state in (CLOSING, HOLDING) and not self.target_is_fresh(now_ms, elapsed_ms):
            return self._latch_fault("target_stale", now_ms)
        if self.state == CLOSING and self._elapsed(
                now_ms, self.state_entered_ms, elapsed_ms) > self.closing_timeout_ms:
            return self._latch_fault("closing_timeout", now_ms)
        if self.state == RELEASING and self._elapsed(
                now_ms, self.state_entered_ms, elapsed_ms) > self.releasing_timeout_ms:
            return self._latch_fault("releasing_timeout", now_ms)
        return None

    def snapshot(self):
        return {
            "state": self.state,
            "link_online": self.link_online,
            "armed": self.armed,
            "target_sequence": self.target_sequence,
            "grip_intent": self.grip_intent,
            "fault_reason": self.fault_reason,
            "safe_stop_required": self.safe_stop_required,
            "event_count": self.event_count,
        }

