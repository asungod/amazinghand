import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "host"))

from session_sequence_model import PeerSessionModel, run_vector  # noqa: E402


class SessionSequenceModelTests(unittest.TestCase):
    def test_all_json_vectors_match_reference_model(self):
        path = PROJECT_ROOT / "protocol" / "SESSION_TEST_VECTORS.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["format_version"], 1)
        self.assertEqual(len(data["cases"]), 6)
        for vector in data["cases"]:
            with self.subTest(vector=vector["name"]):
                self.assertEqual(run_vector(vector), vector["expected"])

    def test_rejects_out_of_range_fields(self):
        model = PeerSessionModel()
        with self.assertRaisesRegex(ValueError, "sequence"):
            model.handle_hello(65536, 1, 2)
        with self.assertRaisesRegex(ValueError, "boot_id"):
            model.handle_hello(0, -1, 2)
        with self.assertRaisesRegex(ValueError, "sequence"):
            model.accept_sequence(-1)


if __name__ == "__main__":
    unittest.main()
