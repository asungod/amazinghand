"""Small, fail-closed client for the Titan OpenSignHand motion protocol.

The MaixCAM2 side does not know servo positions.  It only sends a fixed
``SIGN`` request and consumes the corresponding ``SIGNSTAT`` progress
messages.  Titan remains the owner of the servo mailbox and of all motion
limits.  This module is deliberately dependency-free so it can run in the
MaixPy application and in host-side tests.

``SIGNSTAT`` arguments (protocol version 1) are::

    version, request_uart_sequence, sequence_id, state, result,
    completed_count, last_action

The request UART sequence is the sequence of the SIGN frame, not the
sequence_id of the fixed motion recipe.  A stale or malformed status never
changes the local state.
"""

try:
    from protocol import MAX_UINT16, MAX_UINT32
except Exception:  # pragma: no cover - convenient when copied alone
    MAX_UINT16 = 0xFFFF
    MAX_UINT32 = 0xFFFFFFFF


PROTOCOL_VERSION = 1
SEQUENCE_HELLO = 1
SEQUENCE_FIST = 2
SEQUENCE_V_SIGN = 3
SEQUENCE_POINT = 4
SEQUENCE_THUMBS_UP = 5
SEQUENCE_L_SHAPE = 6
SEQUENCE_OK_PINCH = 7
SEQUENCE_HELLO_WORD = 8
SEQUENCE_THANKS_WORD = 9
SEQUENCE_HELP_SIGNAL = 10
SEQUENCE_NO_WORD = 11
SEQUENCE_ATTENTION_WORD = 12
SEQUENCE_LIKE_WORD = 13
SUPPORTED_SEQUENCE_IDS = (
    SEQUENCE_HELLO,
    SEQUENCE_FIST,
    SEQUENCE_V_SIGN,
    SEQUENCE_POINT,
    SEQUENCE_THUMBS_UP,
    SEQUENCE_L_SHAPE,
    SEQUENCE_OK_PINCH,
    SEQUENCE_HELLO_WORD,
    SEQUENCE_THANKS_WORD,
    SEQUENCE_HELP_SIGNAL,
    SEQUENCE_NO_WORD,
    SEQUENCE_ATTENTION_WORD,
    SEQUENCE_LIKE_WORD,
)

ACTION_START = 1
ACTION_CANCEL = 2
ACTION_HOME = 3
SIGN_ACTION_START = ACTION_START
SIGN_ACTION_CANCEL = ACTION_CANCEL
SIGN_ACTION_HOME = ACTION_HOME

STATE_IDLE = 0
STATE_QUEUED = 1
STATE_RUNNING = 2
STATE_CANCELLING = 3
STATE_HOMING = 4
STATE_COMPLETED = 5
STATE_CANCELLED = 6
STATE_FAILED = 7

RESULT_NONE = 0
RESULT_SUCCEEDED = 1
RESULT_MOTION_FAILED = 2
RESULT_CANCELLED = 3
RESULT_CANCEL_RECOVERY_FAILED = 4
RESULT_HOME_FAILED = 5

ERROR_OK = "OK"
ERROR_MALFORMED_SIGNSTAT = "MALFORMED_SIGNSTAT"
ERROR_UNEXPECTED_REQUEST = "UNEXPECTED_REQUEST"
ERROR_SEQUENCE_MISMATCH = "SEQUENCE_MISMATCH"
ERROR_ACK_REJECTED = "ACK_REJECTED"
ERROR_ACK_TIMEOUT = "ACK_TIMEOUT"
ERROR_STATUS_TIMEOUT = "STATUS_TIMEOUT"
ERROR_SEND_FAILED = "SEND_FAILED"
ERROR_BUSY = "BUSY"
ERROR_UNSUPPORTED_SEQUENCE = "UNSUPPORTED_SEQUENCE"

TERMINAL_STATES = (STATE_COMPLETED, STATE_CANCELLED, STATE_FAILED)


def _now_int(value):
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError("now_ms must be an integer")


class SignMotionController:
    """Track one fixed Titan sign-motion request at a time.

    The class intentionally has no serial write method.  The caller performs
    the actual write through ``write_tracked``/``send_frame`` and calls
    :meth:`note_sent` only after a complete frame was accepted by the UART
    driver.  This prevents a short write from looking like a live action.
    """

    def __init__(
        self,
        sequence_id=SEQUENCE_HELLO,
        ack_timeout_ms=1000,
        status_timeout_ms=1500,
    ):
        sequence_id = int(sequence_id)
        if sequence_id not in SUPPORTED_SEQUENCE_IDS:
            raise ValueError("unsupported sign sequence_id")
        if int(ack_timeout_ms) <= 0 or int(status_timeout_ms) <= 0:
            raise ValueError("timeouts must be positive")
        self.sequence_id = sequence_id
        self.ack_timeout_ms = int(ack_timeout_ms)
        self.status_timeout_ms = int(status_timeout_ms)
        self.state = STATE_IDLE
        self.result = RESULT_NONE
        self.completed_count = 0
        self.last_action = ACTION_START
        self.last_status_ms = None
        self.last_error = ERROR_OK
        self.active_request_seq = None
        self.active_action = None
        self.pending_ack = False
        self.sent_ms = None
        self.last_ack_status = None
        # Main-loop integration uses this to advance its shared 16-bit frame
        # sequence without changing the historical boolean return value of
        # consume_sign_intent().
        self.last_sent_sequence = None

    @property
    def busy(self):
        return bool(
            self.pending_ack
            or self.active_request_seq is not None
            or self.state in (STATE_QUEUED, STATE_RUNNING, STATE_CANCELLING,
                              STATE_HOMING)
        )

    @property
    def active(self):
        return self.busy

    @property
    def idle(self):
        return not self.busy

    def _set_failed(self, error):
        self.state = STATE_FAILED
        self.result = RESULT_MOTION_FAILED
        self.last_error = error
        self.pending_ack = False
        self.active_request_seq = None

    def _validate_uart_seq(self, value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            return None
        if value < 0 or value > MAX_UINT16:
            return None
        return value

    def _validate_action(self, action):
        try:
            action = int(action)
        except (TypeError, ValueError):
            return None
        return action if action in (ACTION_START, ACTION_CANCEL, ACTION_HOME) else None

    def can_start(self):
        return not self.busy and self.state in (STATE_IDLE,) + TERMINAL_STATES

    def can_cancel(self):
        return bool(self.busy or self.state in (STATE_QUEUED, STATE_RUNNING,
                                                 STATE_CANCELLING, STATE_HOMING))

    def begin_request(self, action, request_uart_seq, now_ms=0, sequence_id=None):
        """Reserve a SIGN request before the caller writes its frame.

        Reservation is separate from :meth:`note_sent` so an unsuccessful
        write can be explicitly failed and cannot leave an imaginary action
        running.
        """
        action = self._validate_action(action)
        request_uart_seq = self._validate_uart_seq(request_uart_seq)
        if sequence_id is None:
            sequence_id = self.sequence_id
        try:
            sequence_id = int(sequence_id)
        except (TypeError, ValueError):
            sequence_id = None
        if action is None:
            self.last_error = ERROR_UNEXPECTED_REQUEST
            return False
        if sequence_id not in SUPPORTED_SEQUENCE_IDS:
            self.last_error = ERROR_UNSUPPORTED_SEQUENCE
            return False
        if request_uart_seq is None:
            self.last_error = ERROR_UNEXPECTED_REQUEST
            return False
        if action == ACTION_START and not self.can_start():
            self.last_error = ERROR_BUSY
            return False
        if action == ACTION_CANCEL and not self.can_cancel():
            # Cancellation is idempotent at the protocol boundary.  There is
            # no frame to send when no local motion is pending.
            self.last_error = ERROR_OK
            return False
        if action == ACTION_HOME and self.busy:
            self.last_error = ERROR_BUSY
            return False
        self.sequence_id = sequence_id
        self.active_request_seq = request_uart_seq
        self.active_action = action
        self.pending_ack = False
        self.sent_ms = None
        self.last_ack_status = None
        self.last_status_ms = None
        self.result = RESULT_NONE
        self.last_action = action
        self.last_error = ERROR_OK
        if action == ACTION_HOME:
            self.state = STATE_HOMING
        else:
            self.state = STATE_QUEUED if action == ACTION_START else STATE_CANCELLING
        return True

    # Names used by route/loop adapters and host tests.
    reserve = begin_request
    request = begin_request

    def note_sent(self, request_uart_seq=None, action=None, now_ms=0, sequence_id=None):
        """Mark a fully written SIGN frame as awaiting ACK."""
        if request_uart_seq is None:
            request_uart_seq = self.active_request_seq
        request_uart_seq = self._validate_uart_seq(request_uart_seq)
        if request_uart_seq is None or request_uart_seq != self.active_request_seq:
            self.last_error = ERROR_UNEXPECTED_REQUEST
            return False
        if action is not None and self._validate_action(action) != self.active_action:
            self.last_error = ERROR_UNEXPECTED_REQUEST
            return False
        if sequence_id is not None and int(sequence_id) != self.sequence_id:
            self.last_error = ERROR_UNSUPPORTED_SEQUENCE
            return False
        self.pending_ack = True
        self.sent_ms = _now_int(now_ms)
        self.last_error = ERROR_OK
        return True

    def note_send_failed(self, request_uart_seq=None, error=ERROR_SEND_FAILED):
        if request_uart_seq is not None and self.active_request_seq != request_uart_seq:
            self.last_error = ERROR_UNEXPECTED_REQUEST
            return False
        self._set_failed(error or ERROR_SEND_FAILED)
        return True

    def note_ack(self, request_uart_seq, status, now_ms=0):
        """Consume only the ACK belonging to this SIGN request."""
        request_uart_seq = self._validate_uart_seq(request_uart_seq)
        if request_uart_seq is None or request_uart_seq != self.active_request_seq:
            return False
        try:
            status = int(status)
        except (TypeError, ValueError):
            return False
        self.pending_ack = False
        self.last_ack_status = status
        if status != 0:
            self._set_failed(ERROR_ACK_REJECTED)
            return True
        # If Titan's first SIGNSTAT packet is delayed or lost, the accepted
        # ACK still gives us a bounded status-wait window.  Without this
        # baseline an ACK=0 with no subsequent SIGNSTAT could remain active
        # forever because ``last_status_ms`` would stay unset.
        if self.last_status_ms is None:
            self.last_status_ms = self.sent_ms if self.sent_ms is not None else _now_int(now_ms)
        self.last_error = ERROR_OK
        # Titan's ACK=0 means queued/accepted only.  Keep waiting for
        # SIGNSTAT; it is the only completion authority.
        return True

    acknowledge = note_ack

    def note_ack_timeout(self, request_uart_seq=None):
        if request_uart_seq is not None and request_uart_seq != self.active_request_seq:
            return False
        if not self.pending_ack:
            return False
        self._set_failed(ERROR_ACK_TIMEOUT)
        return True

    def _parse_status(self, message):
        if not isinstance(message, dict) or message.get("type") != "SIGNSTAT":
            return None
        args = message.get("args")
        if not isinstance(args, (tuple, list)) or len(args) != 7:
            return None
        try:
            values = [int(value) for value in args]
        except (TypeError, ValueError):
            return None
        version, request_seq, sequence_id, state, result, count, last_action = values
        if version != PROTOCOL_VERSION:
            return None
        if not 0 <= request_seq <= MAX_UINT16:
            return None
        if sequence_id != self.sequence_id:
            return None
        if state < STATE_IDLE or state > STATE_FAILED:
            return None
        if result < RESULT_NONE or result > RESULT_HOME_FAILED:
            return None
        if count < 0 or count > MAX_UINT32:
            return None
        if last_action not in (ACTION_START, ACTION_CANCEL, ACTION_HOME):
            return None
        return {
            "request_seq": request_seq,
            "sequence_id": sequence_id,
            "state": state,
            "result": result,
            "completed_count": count,
            "last_action": last_action,
        }

    def note_status(self, message, now_ms=0):
        """Apply a valid SIGNSTAT for the currently active request."""
        parsed = self._parse_status(message)
        if parsed is None:
            self.last_error = ERROR_MALFORMED_SIGNSTAT
            return False
        if self.active_request_seq is None or parsed["request_seq"] != self.active_request_seq:
            self.last_error = ERROR_UNEXPECTED_REQUEST
            return False
        expected_actions = (self.active_action,)
        if self.active_action is not None and parsed["last_action"] not in expected_actions:
            self.last_error = ERROR_UNEXPECTED_REQUEST
            return False
        self.state = parsed["state"]
        self.result = parsed["result"]
        self.completed_count = parsed["completed_count"]
        self.last_action = parsed["last_action"]
        self.last_status_ms = _now_int(now_ms)
        self.last_error = ERROR_OK
        if self.state in TERMINAL_STATES:
            self.pending_ack = False
            self.active_request_seq = None
        return True

    handle_status = note_status
    note_sign_status = note_status

    def tick(self, now_ms=0, ack_pending=None, status_fresh=True):
        """Advance timeouts without inventing a completion state."""
        now_ms = _now_int(now_ms)
        if self.active_request_seq is None:
            return self.status()
        if ack_pending is False and self.pending_ack:
            self.note_ack_timeout(self.active_request_seq)
            return self.status()
        if self.pending_ack and self.sent_ms is not None and now_ms - self.sent_ms >= self.ack_timeout_ms:
            self._set_failed(ERROR_ACK_TIMEOUT)
            return self.status()
        if (
            not self.pending_ack
            and self.last_status_ms is not None
            and now_ms - self.last_status_ms >= self.status_timeout_ms
        ):
            self._set_failed(ERROR_STATUS_TIMEOUT)
        return self.status()

    def status(self):
        return {
            "state": self.state,
            "result": self.result,
            "sequence_id": self.sequence_id,
            "request_uart_seq": self.active_request_seq,
            "completed_count": self.completed_count,
            "last_action": self.last_action,
            "pending_ack": bool(self.pending_ack),
            "last_status_ms": self.last_status_ms,
            "last_error": self.last_error,
        }

    snapshot = status


# Compatibility aliases make the narrow module easier to consume without
# forcing callers to import the implementation-specific class name.
SignMotionState = SignMotionController
SignMotionProtocol = SignMotionController
