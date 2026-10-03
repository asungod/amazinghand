import tempfile
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "host"))

from generate_uart_fault_corpus import (  # noqa: E402
    build_cases,
    load_corpus,
    serializable_cases,
    verify_cases,
    write_corpus,
)


class UartFaultCorpusTests(unittest.TestCase):
    def test_all_generated_cases_match_expected_parser_results(self):
        cases = build_cases()
        self.assertEqual(verify_cases(cases), [])
        self.assertEqual(len(cases), 10)
        self.assertIn("crc_error_then_recovery", {case["name"] for case in cases})
        self.assertIn("sequence_rollover", {case["name"] for case in cases})

    def test_serialization_is_deterministic(self):
        first = serializable_cases(build_cases())
        second = serializable_cases(build_cases())
        self.assertEqual(first, second)

    def test_written_corpus_round_trips_and_revalidates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.json"
            write_corpus(path, build_cases())
            loaded = load_corpus(path)
        self.assertEqual(verify_cases(loaded), [])


if __name__ == "__main__":
    unittest.main()
