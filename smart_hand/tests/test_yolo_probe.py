import contextlib
import importlib.util
import io
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIXCAM2_ROOT = PROJECT_ROOT / "maixcam2"
sys.path.insert(0, str(MAIXCAM2_ROOT))


class FakeTime:
    def __init__(self):
        self.now_ms = 0

    def ticks_ms(self):
        return self.now_ms

    @staticmethod
    def ticks_diff(previous_ms, now_ms):
        return now_ms - previous_ms

    def sleep_ms(self, duration_ms):
        self.now_ms += duration_ms


class FakeApp:
    def __init__(self, iterations):
        self.iterations = iterations
        self.completed = 0

    def need_exit(self):
        if self.completed >= self.iterations:
            return True
        self.completed += 1
        return False


class FakeVisionSource:
    def __init__(self):
        self.payloads = [(41, 100, 120, 40, 60, 91), None]

    def read(self):
        return self.payloads.pop(0)

    @staticmethod
    def summary():
        return "mode=test"


def load_probe_module(iterations):
    fake_maix = types.ModuleType("maix")
    fake_maix.app = FakeApp(iterations)
    fake_maix.time = FakeTime()
    fake_maix.display = types.SimpleNamespace()
    fake_maix.image = types.SimpleNamespace(COLOR_RED=0)
    spec = importlib.util.spec_from_file_location(
        "yolo_probe_under_test", MAIXCAM2_ROOT / "yolo_probe.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"maix": fake_maix}):
        spec.loader.exec_module(module)
    return module


class YoloProbeIntegrationTests(unittest.TestCase):
    def test_replay_mode_prints_header_target_and_none_rows(self):
        module = load_probe_module(iterations=2)
        module.SHOW_PREVIEW = False
        module.PRINT_REPLAY_ROWS = True
        module.Yolo11VisionSource = lambda *_args, **_kwargs: FakeVisionSource()
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            module.main()

        text = output.getvalue()
        self.assertIn(
            "REPLAY,time_ms,class_id,center_x,center_y,width,height,confidence",
            text,
        )
        self.assertIn("REPLAY,0,41,100,120,40,60,91", text)
        self.assertIn("REPLAY,10,NONE,,,,,", text)


if __name__ == "__main__":
    unittest.main()
