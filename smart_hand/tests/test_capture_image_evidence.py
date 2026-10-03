"""Same-frame local image pairing contracts using fake SDK JPEG bytes."""
import hashlib
import json
from pathlib import Path
import tempfile
import types
import unittest

from smart_hand.tests.test_capture_detector_diagnostic import capture
from smart_hand.tests.test_capture_hand_identity import DrawingFrame
from smart_hand.tests.test_capture_roi_retry import hand


class Image:
    def __init__(self, data=b"fake-jpeg-from-current-frame"):
        self.data, self.rectangles = data, []
    def width(self):
        return 320
    def height(self):
        return 224
    def crop(self, *rect):
        self.rectangles.append(rect)
        return self
    def to_jpeg(self):
        return self
    def to_bytes(self):
        return self.data


def sample():
    return {"sample_id": "S01-L-IMAGE01-1000-000001",
            "sequence_id": "S01-L-IMAGE01-1000", "timestamp_ms": 1000,
            "landmarks": hand().points[8:]}


class ImageEvidenceTests(unittest.TestCase):
    def test_current_image_pair_is_owned_and_hashed_with_record_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            frame, record = Image(), sample()
            raw = list(record["landmarks"])
            result = capture.save_hand_evidence(frame, record, str(Path(directory)/"samples.jsonl"))
            self.assertEqual(result["status"], "saved")
            self.assertEqual(result["sample_id"], record["sample_id"])
            self.assertEqual(result["timestamp_ms"], 1000)
            self.assertEqual(result["crop_rect"], [68, 63, 96, 150])
            self.assertEqual(frame.rectangles, [(68, 63, 96, 150)])
            self.assertFalse(result["annotated"])
            self.assertEqual(Path(result["path"]).read_bytes(), frame.data)
            self.assertEqual(result["sha256"], hashlib.sha256(frame.data).hexdigest())
            self.assertEqual(record["landmarks"], raw)

    def test_disabled_feature_never_calls_sdk_or_creates_files(self):
        result = capture.save_hand_evidence(object(), sample(), "unused.jsonl", False)
        self.assertEqual(result["status"], "disabled")
        self.assertIsNone(result["path"])

    def test_existing_filename_does_not_overwrite_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            output = str(Path(directory)/"samples.jsonl")
            first = capture.save_hand_evidence(Image(b"first"), sample(), output)
            second = capture.save_hand_evidence(Image(b"replacement"), sample(), output)
            self.assertEqual(second["status"], "failed")
            self.assertIsNone(second["path"])
            self.assertEqual(Path(first["path"]).read_bytes(), b"first")

    def test_codec_failure_empty_and_oversized_payload_do_not_claim_a_pair(self):
        for data in (b"", b"x"*(capture.MAX_EVIDENCE_BYTES+1), "not bytes"):
            with self.subTest(data_type=type(data)), tempfile.TemporaryDirectory() as directory:
                result = capture.save_hand_evidence(Image(data), sample(), str(Path(directory)/"samples.jsonl"))
                self.assertEqual(result["status"], "failed")
                self.assertIsNone(result["path"])
                self.assertFalse(list(Path(directory).rglob("*.jpg")))
        result = capture.save_hand_evidence(object(), sample(), "unused.jsonl")
        self.assertEqual(result["status"], "failed")

    def test_crop_bounds_and_source_pixels_are_not_fabricated(self):
        with tempfile.TemporaryDirectory() as directory:
            record = sample()
            record["landmarks"][0:2] = [-20, -10]
            frame = Image()
            result = capture.save_hand_evidence(frame, record, str(Path(directory)/"samples.jsonl"))
            self.assertEqual(result["crop_rect"][:2], [0, 0])
            self.assertEqual(record["landmarks"][:2], [-20, -10])

    def test_path_traversal_metadata_does_not_create_outside_files(self):
        with tempfile.TemporaryDirectory() as directory:
            record = sample()
            record["sequence_id"] = "../outside"
            result = capture.save_hand_evidence(Image(), record, str(Path(directory)/"samples.jsonl"))
            self.assertEqual(result["status"], "failed")
            self.assertFalse(list(Path(directory).rglob("*.jpg")))

    def test_roi_global_landmarks_choose_original_frame_crop(self):
        with tempfile.TemporaryDirectory() as directory:
            wrapped = capture._CameraFrameHand(hand(), (48, 0, 224, 224))
            record = sample()
            record["landmarks"] = wrapped.points[8:]
            result = capture.save_hand_evidence(Image(), record, str(Path(directory)/"samples.jsonl"))
            self.assertEqual(result["crop_rect"], [116, 63, 96, 150])

    def test_five_device_failed_rectangles_encode_with_even_only_codec(self):
        class EvenOnlyImage(Image):
            def to_jpeg(self):
                _, _, width, height = self.rectangles[-1]
                if width % 2 or height % 2:
                    raise RuntimeError("sz.width % 2 == 0 && sz.height % 2 == 0")
                return self
        failed = [(74, 94, 111, 121), (70, 87, 118, 125),
                  (62, 78, 139, 128), (68, 78, 123, 127),
                  (61, 80, 133, 126)]
        for x, y, width, height in failed:
            with self.subTest(rect=(x, y, width, height)), tempfile.TemporaryDirectory() as directory:
                # Recreate the extrema that produced each failed device crop.
                record = sample()
                record["landmarks"] = [x+12, y+12, 0]*20 + [x+width-13, y+height-13, 0]
                raw = list(record["landmarks"])
                result = capture.save_hand_evidence(EvenOnlyImage(), record, str(Path(directory)/"samples.jsonl"))
                self.assertEqual(result["status"], "saved")
                left, top, w, h = result["crop_rect"]
                self.assertEqual(w % 2, 0)
                self.assertEqual(h % 2, 0)
                self.assertLessEqual(left, x)
                self.assertLessEqual(top, y)
                self.assertGreaterEqual(left+w, x+width)
                self.assertGreaterEqual(top+h, y+height)
                self.assertLessEqual(left+w, 320)
                self.assertLessEqual(top+h, 224)
                self.assertEqual(record["landmarks"], raw)

    def test_crop_at_bottom_right_expands_toward_inside_and_keeps_points(self):
        with tempfile.TemporaryDirectory() as directory:
            record = sample()
            record["landmarks"] = [313, 217, 0]*21
            result = capture.save_hand_evidence(Image(), record, str(Path(directory)/"samples.jsonl"))
            self.assertEqual(result["status"], "saved")
            self.assertEqual(result["crop_rect"], [300, 204, 20, 20])

    def test_unexpandable_odd_full_frame_fails_without_clipping_or_encoding(self):
        class OddImage(Image):
            def width(self):
                return 319
        with tempfile.TemporaryDirectory() as directory:
            record = sample()
            record["landmarks"] = [0, 0, 0]*20 + [318, 223, 0]
            frame = OddImage()
            result = capture.save_hand_evidence(frame, record, str(Path(directory)/"samples.jsonl"))
            self.assertEqual(result["status"], "failed")
            self.assertIsNone(result["path"])
            self.assertFalse(frame.rectangles)
            self.assertFalse(list(Path(directory).rglob("*.jpg")))

    def test_real_loop_saves_before_drawing_and_never_pairs_missing_frame(self):
        state = {"index": -1, "frames": []}
        class Frame(DrawingFrame):
            def to_jpeg(self):
                if self.drawing:
                    raise AssertionError("JPEG captured after annotation")
                return self
            def to_bytes(self):
                return b"current-read-" + str(self.index).encode()
            def crop(self, *_rect):
                return self
        class Camera:
            def __init__(self, *_args):
                pass
            def read(self):
                state["index"] += 1
                frame = Frame()
                frame.index = state["index"]
                state["frames"].append(frame)
                return frame
            def close(self):
                pass
        class NN:
            def __init__(self, **_kwargs):
                pass
            def input_format(self):
                return "fake"
            def detect(self, *_args, **_kwargs):
                return [] if state["index"] == 1 else [hand()]
            def draw_hand(self, frame, *_args, **_kwargs):
                frame.draw_string(0, 0, "drawn")
        screen = types.SimpleNamespace(width=lambda:320, height=lambda:224, show=lambda _f:None)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"records.jsonl"
            capture.run_capture(
                capture.CaptureConfig(consent=True, countdown_seconds=0, target_samples=2,
                                      max_capture_ms=1200, output_path=str(path)),
                app_module=types.SimpleNamespace(need_exit=lambda:False),
                camera_module=types.SimpleNamespace(Camera=Camera),
                display_module=types.SimpleNamespace(Display=lambda:screen),
                image_module=types.SimpleNamespace(COLOR_RED="red"),
                nn_module=types.SimpleNamespace(HandLandmarks=NN),
                time_module=types.SimpleNamespace(ticks_ms=lambda:state["index"]*200,
                                                  ticks_diff=lambda a,b:b-a, sleep_ms=lambda _ms:None))
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([r["frame_index"] for r in rows], [1, 4])
            self.assertEqual(rows[1]["stable_ms"], 200)
            self.assertEqual(len(list(Path(directory).rglob("*.jpg"))), 2)
            for row, index in zip(rows, (0, 3)):
                image = row["hand_image_evidence"]
                self.assertEqual(image["status"], "saved")
                self.assertEqual(Path(image["path"]).read_bytes(), b"current-read-"+str(index).encode())


if __name__ == "__main__":
    unittest.main()
