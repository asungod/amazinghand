import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))

from rehab_imitation import ImitationSessionController  # noqa: E402
from rehab_session_log import CSV_HEADER, SessionCsvLogger  # noqa: E402


def elapsed(now_ms, previous_ms):
    return now_ms - previous_ms


class SessionCsvLoggerTests(unittest.TestCase):
    def test_complete_and_timeout_rows_are_append_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.csv"
            logger = SessionCsvLogger(str(path))

            complete = ImitationSessionController(goal_repetitions=1)
            complete.start(100)
            complete.tracker.repetitions = 1
            complete.state = "COMPLETE"
            complete.completed_ms = 1100
            self.assertEqual(logger.append(complete, 1100, elapsed, 17600), 1)

            timeout = ImitationSessionController(
                goal_repetitions=5, timeout_ms=1000
            )
            timeout.start(2000)
            timeout.tracker.repetitions = 2
            timeout.state = "TIMEOUT"
            timeout.completed_ms = 3000
            self.assertEqual(logger.append(timeout, 3000, elapsed, None), 2)

            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0], CSV_HEADER.strip())
            self.assertEqual(lines[1], "1,1,COMPLETE,1,1,100,17600,1000,1000")
            self.assertEqual(lines[2], "1,2,TIMEOUT,2,5,40,-1,1000,500")

            reason_path = Path(str(path) + ".reason.csv")
            self.assertEqual(logger.append_reason(complete, session_number=1), 1)
            self.assertEqual(logger.append_reason(timeout, session_number=2), 2)
            self.assertEqual(
                reason_path.read_text(encoding="utf-8").splitlines(),
                [
                    "schema,session,outcome,termination_reason",
                    "1,1,COMPLETE,goal_reached",
                    "1,2,TIMEOUT,imitation_timeout",
                ],
            )

            resumed = SessionCsvLogger(str(path))
            self.assertEqual(resumed.next_session, 3)

    def test_nonterminal_session_is_not_written(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.csv"
            logger = SessionCsvLogger(str(path))
            active = ImitationSessionController(goal_repetitions=1)
            active.start(0)
            self.assertIsNone(logger.append(active, 100, elapsed))
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
