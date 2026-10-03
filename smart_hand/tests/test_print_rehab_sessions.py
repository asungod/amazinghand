import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))

import print_rehab_sessions  # noqa: E402


class PrintRehabSessionsTests(unittest.TestCase):
    def test_main_prints_reason_sidecar(self):
        paths = {
            print_rehab_sessions.SESSION_LOG_PATH: "session\n",
            print_rehab_sessions.QUALITY_LOG_PATH: "quality\n",
            print_rehab_sessions.REASON_LOG_PATH: "reason\n",
        }

        def open_path(path, mode="r"):
            self.assertEqual(mode, "r")
            return io.StringIO(paths[path])

        output = io.StringIO()
        with patch("builtins.open", side_effect=open_path), redirect_stdout(output):
            result = print_rehab_sessions.main()

        self.assertEqual(result, 0)
        rendered = output.getvalue()
        self.assertIn("SESSION CSV BEGIN\nsession\nSESSION CSV END", rendered)
        self.assertIn("QUALITY CSV BEGIN\nquality\nQUALITY CSV END", rendered)
        self.assertIn("REASON CSV BEGIN\nreason\nREASON CSV END", rendered)

    def test_missing_sidecars_do_not_change_success_return_code(self):
        def open_path(path, mode="r"):
            if path == print_rehab_sessions.SESSION_LOG_PATH:
                return io.StringIO("session\n")
            raise OSError("missing sidecar")

        output = io.StringIO()
        with patch("builtins.open", side_effect=open_path), redirect_stdout(output):
            result = print_rehab_sessions.main()

        self.assertEqual(result, 0)
        rendered = output.getvalue()
        self.assertIn("QUALITY CSV ERROR: missing sidecar", rendered)
        self.assertIn("REASON CSV ERROR: missing sidecar", rendered)
        self.assertNotIn("QUALITY CSV BEGIN\n\nQUALITY CSV END", rendered)
        self.assertNotIn("REASON CSV BEGIN\n\nREASON CSV END", rendered)


if __name__ == "__main__":
    unittest.main()
