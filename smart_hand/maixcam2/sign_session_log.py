"""Append-only CSV logging for independent sign-shape training sessions.

The file produced here is intentionally separate from the legacy
``smart_hand_rehab_sessions.csv`` format.  A row is written only after a
terminal sign lesson state (COMPLETE, REVIEWED, TIMEOUT, CANCELLED, or FAULT), and
logging errors do not get to authorize hardware actions.
"""

DEFAULT_PATH = "smart_hand_sign_sessions.csv"
TERMINAL_STATES = ("COMPLETE", "REVIEWED", "TIMEOUT", "CANCELLED", "FAULT")
CSV_COLUMNS = (
    "schema",
    "session",
    "lesson_id",
    "lesson_name",
    "prototype_id",
    "outcome",
    "state",
    "started_ms",
    "ended_ms",
    "duration_ms",
    "gesture_id",
    "confidence",
    "stable_ms",
    "valid",
    "error_code",
    "demo_mode",
    "mechanical_pose",
)
CSV_HEADER = ",".join(CSV_COLUMNS) + "\n"


def _open_text(path, mode):
    """Prefer UTF-8 while retaining compatibility with small MicroPython builds."""
    try:
        return open(path, mode, encoding="utf-8")
    except TypeError:
        return open(path, mode)


def _value(source, key, default=None):
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _csv_line(values):
    """Serialize one row without requiring a heavyweight CSV module."""
    fields = []
    for value in values:
        text = "" if value is None else str(value)
        if any(char in text for char in (",", "\"", "\n", "\r")):
            text = '"' + text.replace('"', '""') + '"'
        fields.append(text)
    return ",".join(fields) + "\n"


class SignSessionCsvLogger:
    """Append one row per terminal sign lesson session."""

    def __init__(self, path=DEFAULT_PATH):
        self.path = str(path)
        self.next_session = self._discover_next_session()
        self._last_controller = None
        self._last_session_number = None

    def _discover_next_session(self):
        largest = 0
        try:
            with _open_text(self.path, "r") as handle:
                lines = handle.readlines()
            for line in lines[1:]:
                fields = line.strip().split(",", 2)
                if len(fields) < 2:
                    continue
                try:
                    largest = max(largest, int(fields[1]))
                except (TypeError, ValueError):
                    continue
        except (OSError, UnicodeError):
            return 1
        return largest + 1

    @staticmethod
    def _terminal_state(controller_or_status):
        state = _value(controller_or_status, "state")
        return state if state in TERMINAL_STATES else None

    def _status_from_controller(self, controller, now_ms):
        status_fn = getattr(controller, "status", None)
        if status_fn is not None:
            try:
                return status_fn()
            except TypeError:
                return status_fn(now_ms)
        return {
            "state": _value(controller, "state"),
            "lesson_id": _value(controller, "lesson_id"),
            "lesson": _value(controller, "lesson"),
            "gesture_id": _value(controller, "gesture_id", "UNKNOWN"),
            "confidence": _value(controller, "confidence", 0.0),
            "stable_ms": _value(controller, "stable_ms", 0),
            "valid": _value(controller, "valid", False),
            "error_code": _value(controller, "error_code", ""),
            "started_ms": _value(controller, "started_ms"),
            "completed_ms": _value(controller, "completed_ms"),
            "session_token": _value(controller, "session_token"),
        }

    def _session_identity(self, controller, status):
        """Identify one controller run without conflating reset sessions."""
        # SignLessonController exposes a monotonically increasing token.  The
        # remaining fields keep this logger safe for lightweight test doubles
        # and older callers that only expose a status mapping.
        token = _value(controller, "session_token", _value(status, "session_token"))
        if token is not None:
            return ("token", token)
        return (
            "legacy",
            _value(status, "lesson_id"),
            _value(status, "started_ms"),
        )

    def _row_values(self, session_number, status, now_ms, result=None):
        lesson = _value(status, "lesson", None)
        if lesson is None:
            lesson = {}
        if result is None:
            result = status
        started_ms = _value(status, "started_ms")
        ended_ms = _value(status, "completed_ms")
        if ended_ms is None:
            ended_ms = now_ms
        if started_ms is None:
            duration_ms = -1
        else:
            duration_ms = max(0, int(ended_ms) - int(started_ms))
        confidence = _value(result, "confidence", 0.0)
        try:
            confidence = round(float(confidence), 4)
        except (TypeError, ValueError):
            confidence = 0.0
        return [
            1,
            session_number,
            _value(status, "lesson_id", _value(lesson, "lesson_id", "")),
            _value(lesson, "name_zh", _value(lesson, "chinese_name", "")),
            _value(lesson, "prototype_id", ""),
            _value(status, "state", ""),
            _value(status, "state", ""),
            "" if started_ms is None else int(started_ms),
            "" if ended_ms is None else int(ended_ms),
            duration_ms,
            _value(result, "gesture_id", "UNKNOWN"),
            confidence,
            int(_value(result, "stable_ms", 0) or 0),
            1 if bool(_value(result, "valid", False)) else 0,
            _value(status, "error_code", _value(result, "error_code", "")),
            _value(lesson, "demo_mode", ""),
            "" if _value(lesson, "mechanical_pose") is None else _value(lesson, "mechanical_pose"),
        ]

    def append(self, controller, now_ms=None, result=None):
        """Append a terminal controller session, returning its session number.

        Calls for a non-terminal session return ``None``.  Repeated calls for
        the same controller after the first write are idempotent.
        """
        state = self._terminal_state(controller)
        if state is None:
            return None
        previous = getattr(controller, "_sign_log_session_number", None)
        now_ms_for_status = now_ms
        if now_ms_for_status is None:
            now_ms_for_status = _value(controller, "completed_ms")
        if now_ms_for_status is None:
            now_ms_for_status = 0
        status = self._status_from_controller(controller, int(now_ms_for_status))
        identity = self._session_identity(controller, status)
        if (
            previous is not None
            and getattr(controller, "_sign_log_identity", None) == identity
        ):
            return previous
        session_number = self.append_status(status, now_ms_for_status, result=result)
        try:
            setattr(controller, "_sign_log_session_number", session_number)
            setattr(controller, "_sign_log_identity", identity)
        except Exception:
            pass
        return session_number

    def append_status(self, status, now_ms=None, result=None):
        """Append a status mapping for integrations without a controller."""
        if self._terminal_state(status) is None:
            return None
        if now_ms is None:
            now_ms = _value(status, "completed_ms")
        if now_ms is None:
            now_ms = 0
        session_number = self.next_session
        row = self._row_values(session_number, status, int(now_ms), result=result)
        need_header = False
        try:
            with _open_text(self.path, "r") as handle:
                need_header = not bool(handle.read(1))
        except (OSError, UnicodeError):
            need_header = True
        with _open_text(self.path, "a") as handle:
            if need_header:
                handle.write(CSV_HEADER)
            handle.write(_csv_line(row))
        self.next_session += 1
        self._last_session_number = session_number
        return session_number

    # Alias for route code that treats a snapshot as the log payload.
    append_snapshot = append_status

    @property
    def last_session_number(self):
        return self._last_session_number


SessionCsvLogger = SignSessionCsvLogger
