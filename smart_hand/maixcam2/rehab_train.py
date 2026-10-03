"""Fail-closed explicit rehabilitation-training request controller.

This module has no Maix imports so its release-edge and authority gating can be
tested offline.  A TRAIN request is never generated from object detection
alone; an enabled on-screen button must be pressed and released inside its
mapped display rectangle.
"""

TRAIN_MODE_REHAB = 1
TRAIN_ACK_ACCEPTED = 0
TRAIN_ACK_INVALID = 1
TRAIN_ACK_UNSUPPORTED = 2
TRAIN_ACK_BLOCKED = 3
TRAIN_ACK_BUSY = 4
TRAINSTAT_VERSION = 1
TRAINSTAT_QUEUED = 1
TRAINSTAT_RUNNING = 2
TRAINSTAT_SUCCEEDED = 3
TRAINSTAT_FAILED = 4


def authority_allows_training(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get("ver") is None:
        return False
    return bool(
        snapshot.get("link_online")
        and snapshot.get("have_vision")
        and not snapshot.get("vision_stale")
        and snapshot.get("have_actionable")
        and snapshot.get("pose") == 0
        and snapshot.get("gate_present")
        and not snapshot.get("gate_fault")
    )


class TrainButtonController:
    def __init__(
        self,
        ack_timeout_ms=1000,
        run_timeout_ms=30000,
        terminal_hold_ms=2000,
    ):
        self.ack_timeout_ms = ack_timeout_ms
        self.run_timeout_ms = run_timeout_ms
        self.terminal_hold_ms = terminal_hold_ms
        self.display_rect = None
        self.pressed_inside = False
        self.last_pressed = False
        self.pending_seq = None
        self.pending_since_ms = None
        self.active_seq = None
        self.accepted_since_ms = None
        self.terminal_since_ms = None
        self.titan_completed_count = 0
        self.session_baseline_count = None
        self.session_completed_count = 0
        self.last_duration_ms = None
        self.last_result_code = 0
        self.state = "WAIT_TARGET"

    def set_display_rect(self, rect):
        self.display_rect = tuple(rect) if rect is not None else None

    def _inside(self, x, y):
        if self.display_rect is None:
            return False
        left, top, width, height = self.display_rect
        return left <= x < left + width and top <= y < top + height

    def enabled(self, snapshot, now_ms, elapsed_ms):
        if (
            self.pending_seq is not None
            or self.active_seq is not None
            or not authority_allows_training(snapshot)
        ):
            return False
        if self.terminal_since_ms is not None and elapsed_ms(
            now_ms, self.terminal_since_ms
        ) < self.terminal_hold_ms:
            return False
        return True

    def update_touch(self, x, y, pressed, enabled):
        inside = self._inside(x, y)
        emit = False
        if pressed and not self.last_pressed:
            self.pressed_inside = bool(enabled and inside)
        elif not pressed and self.last_pressed:
            emit = bool(enabled and inside and self.pressed_inside)
            self.pressed_inside = False
        self.last_pressed = bool(pressed)
        return emit

    def note_sent(self, sequence, now_ms):
        self.pending_seq = sequence
        self.pending_since_ms = now_ms
        self.state = "REQUESTED"

    def note_ack(self, sequence, status, now_ms):
        if sequence != self.pending_seq:
            return False
        self.pending_seq = None
        self.pending_since_ms = None
        if status == TRAIN_ACK_ACCEPTED:
            self.active_seq = sequence
            self.accepted_since_ms = now_ms
            self.state = "QUEUED"
        elif status == TRAIN_ACK_BUSY:
            self.state = "BUSY"
        elif status == TRAIN_ACK_BLOCKED:
            self.state = "BLOCKED"
        else:
            self.state = "REJECTED"
        return True

    def note_train_status(self, message, now_ms, elapsed_ms):
        if not isinstance(message, dict) or message.get("type") != "TRAINSTAT":
            return False
        args = message.get("args")
        if not isinstance(args, list) or len(args) != 5:
            return False
        version, request_seq, state, result_code, completed_count = args
        if (
            version != TRAINSTAT_VERSION
            or request_seq != self.active_seq
            or state not in (
                TRAINSTAT_QUEUED,
                TRAINSTAT_RUNNING,
                TRAINSTAT_SUCCEEDED,
                TRAINSTAT_FAILED,
            )
        ):
            return False

        self.last_result_code = result_code
        if state == TRAINSTAT_QUEUED:
            self.state = "QUEUED"
        elif state == TRAINSTAT_RUNNING:
            self.state = "RUNNING"
        else:
            self.titan_completed_count = completed_count
            if state == TRAINSTAT_SUCCEEDED:
                if (
                    self.session_baseline_count is None
                    or completed_count <= self.session_baseline_count
                ):
                    self.session_baseline_count = max(0, completed_count - 1)
                self.session_completed_count = (
                    completed_count - self.session_baseline_count
                )
            if self.accepted_since_ms is not None:
                self.last_duration_ms = elapsed_ms(
                    now_ms, self.accepted_since_ms
                )
            self.active_seq = None
            self.accepted_since_ms = None
            self.terminal_since_ms = now_ms
            self.state = (
                "COMPLETED" if state == TRAINSTAT_SUCCEEDED else "FAILED"
            )
        return True

    def expire(self, now_ms, elapsed_ms):
        if self.pending_seq is not None:
            if elapsed_ms(now_ms, self.pending_since_ms) < self.ack_timeout_ms:
                return False
            self.pending_seq = None
            self.pending_since_ms = None
            self.state = "ACK_TIMEOUT"
            return True
        if self.active_seq is not None:
            if elapsed_ms(now_ms, self.accepted_since_ms) < self.run_timeout_ms:
                return False
            self.active_seq = None
            self.accepted_since_ms = None
            self.terminal_since_ms = now_ms
            self.state = "STATUS_TIMEOUT"
            return True
        return False

    def status_line(self, enabled):
        if enabled:
            return "TRAIN READY - TAP TO START"
        if self.state == "COMPLETED":
            duration_seconds = (
                self.last_duration_ms / 1000.0
                if self.last_duration_ms is not None
                else -1.0
            )
            return "TRAIN COMPLETE REP={} {:.1f}s".format(
                self.session_completed_count,
                duration_seconds,
            )
        if self.state == "FAILED":
            return "TRAIN FAILED code={}".format(self.last_result_code)
        return "TRAIN {}".format(self.state)
