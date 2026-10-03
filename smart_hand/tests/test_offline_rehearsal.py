import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "host"))

from run_offline_rehearsal import run_rehearsal  # noqa: E402


class OfflineRehearsalTests(unittest.TestCase):
    def test_normal_failure_and_physical_block_paths(self):
        result = run_rehearsal(PROJECT_ROOT)

        self.assertEqual(result["result"], "PASS")
        self.assertFalse(result["hardware_accessed"])
        self.assertGreater(result["vision"]["accepted"], 0)
        self.assertGreater(result["vision"]["rejected"], 0)
        self.assertEqual(
            result["execution_failure_path"]["result"], "safe_stop_required"
        )
        self.assertEqual(result["execution_failure_path"]["final_state"], "FAULT")
        self.assertEqual(result["uart_fault_cases"], 10)
        self.assertFalse(result["physical_motion"]["authorized"])


if __name__ == "__main__":
    unittest.main()
