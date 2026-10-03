"""Offline snapshot test entry; no device or live provider credentials needed."""
from pathlib import Path
import argparse
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODULES = (
    'test_accessible_context', 'test_course_report_quality', 'test_web_stream',
    'test_sign_core', 'test_sign_integration', 'test_maix_main', 'test_protocol',
    'test_live_sidecar', 'test_sign_sequence', 'test_sign_detector_retry',
    'test_ai_course_advice_proxy', 'test_sign_landmark_capture',
    'test_capture_analysis', 'test_capture_detector_diagnostic',
    'test_capture_roi_retry', 'test_capture_hand_identity',
    'test_capture_image_evidence',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full', action='store_true',
                        help='Include historical suites and optional SDK/firmware dependencies; known failures remain.')
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / 'smart_hand'))
    loader = unittest.defaultTestLoader
    suite = loader.discover(str(ROOT / 'smart_hand/tests')) if args.full else loader.loadTestsFromNames(
        ['smart_hand.tests.' + module for module in MODULES])
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
