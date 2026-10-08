"""Run the teaching application's host tests from the repository root."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODULES = (
    'test_offline_demo', 'test_ai_advice_provenance', 'test_step_guidance',
    'test_sign_sequence', 'test_web_stream', 'test_course_report_quality',
    'test_accessible_context', 'test_sign_integration', 'test_maix_main',
    'test_sign_core', 'test_ai_course_advice_proxy', 'test_protocol',
    'test_live_sidecar', 'test_sign_detector_retry',
    'test_gesture_misclassification_evidence', 'test_manual_course_review',
    'test_presentation_finalization', 'test_gesture_palm_direction',
)


def main():
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / 'smart_hand'))
    suite = unittest.defaultTestLoader.loadTestsFromNames(
        ['smart_hand.tests.' + name for name in MODULES])
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
