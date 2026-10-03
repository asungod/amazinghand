"""Append-only rehabilitation session logs."""

import os

CSV_HEADER = (
    "schema,session,outcome,repetitions,goal,completion_pct,"
    "demo_ms,imitation_ms,avg_rep_ms\n"
)
QUALITY_CSV_HEADER = (
    "schema,session,quality_status,rhythm_status,hold_status,"
    "pace_avg_ms,pace_min_ms,pace_max_ms,fast_count,slow_count,"
    "short_hold_count,valid_frame_pct\n"
)
REASON_CSV_HEADER = "schema,session,outcome,termination_reason\n"
DEFAULT_REASON_BY_STATE = {
    "COMPLETE": "goal_reached",
    "TIMEOUT": "imitation_timeout",
}


class SessionCsvLogger:
    def __init__(self, path="/root/smart_hand_rehab_sessions.csv"):
        self.path = path
        self.next_session = self._discover_next_session()

    def _discover_next_session(self):
        try:
            with open(self.path, "r") as handle:
                lines = handle.readlines()
        except OSError:
            return 1
        rows = [line for line in lines[1:] if line.strip()]
        return len(rows) + 1

    def append(self, controller, now_ms, elapsed_ms, demo_ms=None):
        if controller.state not in ("COMPLETE", "TIMEOUT"):
            return None
        imitation_ms = controller.duration_ms(now_ms, elapsed_ms)
        average_ms = controller.average_repetition_ms(now_ms, elapsed_ms)
        row = "1,{},{},{},{},{},{},{},{}\n".format(
            self.next_session, controller.state, controller.repetitions,
            controller.goal_repetitions, controller.completion_percent(),
            -1 if demo_ms is None else int(round(demo_ms)),
            int(round(imitation_ms)), -1 if average_ms is None else int(round(average_ms)),
        )
        need_header = False
        try:
            with open(self.path, "r") as handle:
                need_header = not bool(handle.read(1))
        except OSError:
            need_header = True
        with open(self.path, "a") as handle:
            if need_header:
                handle.write(CSV_HEADER)
            handle.write(row)
        written_session = self.next_session
        self.next_session += 1
        return written_session

    def append_quality(self, controller, *, session_number, now_ms=None, path=None):
        """Best-effort quality sidecar; failures never affect training."""
        if controller.state not in ("COMPLETE", "TIMEOUT"):
            return None
        quality = getattr(controller, "quality_tracker", None)
        if quality is None:
            return None
        if type(session_number) is not int or session_number < 1:
            raise ValueError("session_number must be a positive integer")
        if path is None:
            target = os.fspath(self.path) + ".quality.csv"
        else:
            target = os.fspath(path)
        existing_sessions = set()
        try:
            with open(target, "r") as handle:
                for line in handle:
                    fields = line.strip().split(",")
                    if len(fields) >= 2 and fields[0] == "1":
                        try:
                            existing_sessions.add(int(fields[1]))
                        except ValueError:
                            pass
        except OSError:
            pass
        if session_number in existing_sessions:
            return session_number
        try:
            data = quality.summary()
        except Exception:
            return None
        row = "1,{},{},{},{},{},{},{},{},{},{},{}\n".format(
            session_number, data["quality_status"], data["rhythm_status"],
            data["hold_status"], -1 if data["pace_avg_ms"] is None else data["pace_avg_ms"],
            -1 if data["pace_min_ms"] is None else data["pace_min_ms"],
            -1 if data["pace_max_ms"] is None else data["pace_max_ms"],
            data["fast_count"], data["slow_count"], data["short_hold_count"],
            -1 if data["valid_frame_pct"] is None else data["valid_frame_pct"],
        )
        try:
            need_header = True
            try:
                with open(target, "r") as handle:
                    need_header = not bool(handle.read(1))
            except OSError:
                pass
            with open(target, "a") as handle:
                if need_header:
                    handle.write(QUALITY_CSV_HEADER)
                handle.write(row)
            return session_number
        except OSError:
            return None

    def append_reason(self, controller, *, session_number, path=None):
        """Best-effort terminal reason sidecar; the legacy CSV stays nine columns."""
        if controller.state not in ("COMPLETE", "TIMEOUT"):
            return None
        if type(session_number) is not int or session_number < 1:
            raise ValueError("session_number must be a positive integer")
        reason = getattr(controller, "termination_reason", None)
        if not reason:
            reason = DEFAULT_REASON_BY_STATE.get(controller.state)
        if not reason:
            return None
        target = os.fspath(path) if path is not None else os.fspath(self.path) + ".reason.csv"
        existing_sessions = set()
        try:
            with open(target, "r") as handle:
                for line in handle:
                    fields = line.strip().split(",")
                    if len(fields) >= 2 and fields[0] == "1":
                        try:
                            existing_sessions.add(int(fields[1]))
                        except ValueError:
                            pass
        except OSError:
            pass
        if session_number in existing_sessions:
            return session_number
        try:
            need_header = True
            try:
                with open(target, "r") as handle:
                    need_header = not bool(handle.read(1))
            except OSError:
                pass
            with open(target, "a") as handle:
                if need_header:
                    handle.write(REASON_CSV_HEADER)
                handle.write("1,{},{},{}\n".format(
                    session_number, controller.state, reason
                ))
            return session_number
        except OSError:
            return None
