"""Lazy MaixCAM2 hand-landmark source used only during user imitation."""

from hand_rehab_tracker import classify_openness, hand_openness
from sign_sequence import motion_evidence


class HandLandmarksVisionSource:
    def __init__(
        self,
        model_path="/root/models/hand_landmarks.mud",
        confidence=0.7,
        iou=0.45,
        landmark_confidence=0.8,
        classifier=None,
        sign_detector_retry=False,
    ):
        from maix import camera, nn

        self.detector = nn.HandLandmarks(model=model_path)
        self.camera = camera.Camera(320, 224, self.detector.input_format())
        self.confidence = confidence
        self.iou = iou
        self.landmark_confidence = landmark_confidence
        self.sign_detector_retry = sign_detector_retry is True
        self.last_detection_profile = None
        self.last_detection_attempts = 0
        self.last_frame = None
        self.last_hand = None
        self.last_posture = None
        self.last_score = None
        # Sign recognition is an opt-in adapter.  The existing rehab
        # ``read()`` path remains openness-only when no classifier is passed.
        self.classifier = classifier
        self.last_recognition = {
            "gesture_id": None,
            "confidence": 0.0,
            "stable_ms": 0,
            "valid": False,
            "error_code": "not_started",
        }
        self.frames = 0
        self.no_hand = 0

    def read(self):
        frame = self.camera.read()
        objects = self.detector.detect(
            frame,
            conf_th=self.confidence,
            iou_th=self.iou,
            conf_th2=self.landmark_confidence,
        )
        self.last_frame = frame
        self.frames += 1
        if not objects:
            self.last_hand = None
            self.last_posture = None
            self.last_score = None
            self.no_hand += 1
            return None
        hand = max(objects, key=lambda obj: obj.w * obj.h)
        score = hand_openness(hand.points[8 : 8 + 63])
        self.last_hand = hand
        self.last_score = score
        self.last_posture = classify_openness(score)
        return self.last_posture

    @staticmethod
    def _normalize_recognition(result):
        """Normalize classifier output to the small sign integration contract."""
        if isinstance(result, dict):
            get = result.get
        else:
            get = lambda key, default=None: getattr(result, key, default)
        if isinstance(result, (tuple, list)):
            values = list(result)
            result = {
                "gesture_id": values[0] if len(values) > 0 else None,
                "confidence": values[1] if len(values) > 1 else 0.0,
                "stable_ms": values[2] if len(values) > 2 else 0,
                "valid": values[3] if len(values) > 3 else False,
                "error_code": values[4] if len(values) > 4 else None,
            }
            get = result.get
        gesture_id = get("gesture_id")
        confidence = get("confidence", 0.0)
        stable_ms = get("stable_ms", 0)
        valid = get("valid", False)
        error_code = get("error_code")
        if type(confidence) not in (int, float) or confidence < 0:
            confidence = 0.0
        if type(stable_ms) is not int or stable_ms < 0:
            stable_ms = 0
        if type(valid) is not bool:
            valid = False
        if gesture_id is not None and not isinstance(gesture_id, (str, int)):
            gesture_id = str(gesture_id)
        if error_code is not None and not isinstance(error_code, str):
            error_code = str(error_code)
        normalized = {
            "gesture_id": gesture_id,
            "confidence": confidence,
            "stable_ms": stable_ms,
            "valid": valid,
            "error_code": error_code,
        }
        # Expose bounded geometry diagnostics, never raw points or frames.
        extensions = get("finger_extension")
        if isinstance(extensions, (tuple, list)) and len(extensions) == 4:
            if all(type(value) in (int, float) and 0 <= value <= 1 for value in extensions):
                debug = {"finger_extension": [round(float(value), 3) for value in extensions]}
                for key in ("thumb_extension", "thumb_index_gap", "tip_gap"):
                    value = get(key)
                    if type(value) in (int, float) and 0 <= value <= 10:
                        debug[key] = round(float(value), 3)
                candidate = get("top_candidate")
                if isinstance(candidate, str) and len(candidate) <= 24:
                    debug["top_candidate"] = candidate
                normalized["shape_debug"] = debug
        return normalized

    @staticmethod
    def _call_classifier(method, points, now_ms):
        if now_ms is not None:
            try:
                return method(points, now_ms=now_ms)
            except TypeError:
                pass
        return method(points)

    def _classify_landmarks(self, points, now_ms=None):
        classifier = self.classifier
        if classifier is None:
            return {
                "gesture_id": None,
                "confidence": 0.0,
                "stable_ms": 0,
                "valid": False,
                "error_code": "classifier_unavailable",
            }
        try:
            if callable(classifier):
                result = self._call_classifier(classifier, points, now_ms)
            else:
                result = None
                for method_name in (
                    "observe", "classify", "predict", "recognize", "infer"
                ):
                    method = getattr(classifier, method_name, None)
                    if callable(method):
                        result = self._call_classifier(method, points, now_ms)
                        break
                if result is None:
                    return {
                        "gesture_id": None,
                        "confidence": 0.0,
                        "stable_ms": 0,
                        "valid": False,
                        "error_code": "classifier_interface",
                    }
            normalized = self._normalize_recognition(result)
            if not normalized["valid"] and normalized["error_code"] is None:
                normalized["error_code"] = "invalid_prediction"
            return normalized
        except Exception as exc:
            reset = getattr(classifier, "reset", None)
            if callable(reset):
                reset()
            return {
                "gesture_id": None,
                "confidence": 0.0,
                "stable_ms": 0,
                "valid": False,
                "error_code": "classifier_{}".format(type(exc).__name__),
            }

    def read_sign(self, now_ms=None):
        """Read one landmark frame for sign training.

        This shares the existing Maix hand-landmark detector but does not
        alter the rehab posture result. Successful SDK reads return a complete
        recognition mapping, including no-hand and unknown. SDK/geometry
        errors clear the hold and propagate to main's vision-failure gate.
        """
        try:
            frame = self.camera.read()
            self.last_frame = frame
            self.frames += 1
            self.last_detection_attempts = 1
            self.last_detection_profile = None
            objects = self.detector.detect(
                frame, conf_th=self.confidence, iou_th=self.iou,
                conf_th2=self.landmark_confidence,
            )
            if objects:
                self.last_detection_profile = "baseline"
            elif self.sign_detector_retry and self.confidence > 0.5:
                # Exactly one fresh, same-frame retry. Keep the second-stage
                # presence threshold; no cached points, ROI or label forcing.
                self.last_detection_attempts = 2
                objects = self.detector.detect(
                    frame, conf_th=0.5, iou_th=self.iou,
                    conf_th2=self.landmark_confidence,
                )
                if objects:
                    self.last_detection_profile = "detector_relaxed"
            if not objects:
                # The classifier must see the gap, otherwise its previous
                # candidate could accrue stable_ms while the hand is absent.
                self._classify_landmarks(None, now_ms=now_ms)
                self.last_hand = None
                self.last_posture = None
                self.last_score = None
                self.no_hand += 1
                self.last_recognition = {
                    "gesture_id": None,
                    "confidence": 0.0,
                    "stable_ms": 0,
                    "valid": False,
                    "error_code": "hand_not_found",
                }
                return dict(self.last_recognition)
            hand = max(objects, key=lambda obj: obj.w * obj.h)
            self.last_hand = hand
            self.last_score = hand_openness(hand.points[8 : 8 + 63])
            self.last_posture = classify_openness(self.last_score)
            self.last_recognition = self._classify_landmarks(
                hand.points[8 : 8 + 63], now_ms=now_ms
            )
            self.last_recognition["motion_evidence"] = motion_evidence(hand.points[8 : 8 + 63])
            return dict(self.last_recognition)
        except Exception:
            # Camera/detector/geometry failures also break continuous holds.
            self._classify_landmarks(None, now_ms=now_ms)
            self.last_frame = None
            self.last_hand = None
            self.last_posture = None
            self.last_score = None
            self.last_recognition = {
                "gesture_id": None,
                "confidence": 0.0,
                "stable_ms": 0,
                "valid": False,
                "error_code": "vision_read_failed",
            }
            raise

    def draw_hand(self, frame):
        if self.last_hand is not None:
            self.detector.draw_hand(
                frame,
                self.last_hand.class_id,
                self.last_hand.points,
                4,
                10,
                box=True,
            )

    def close(self):
        import gc

        self.last_frame = None
        self.last_hand = None
        self.camera = None
        self.detector = None
        self.classifier = None
        self.last_recognition = {
            "gesture_id": None,
            "confidence": 0.0,
            "stable_ms": 0,
            "valid": False,
            "error_code": "closed",
        }
        gc.collect()

    def summary(self):
        return "mode=hand frames={} no_hand={}".format(
            self.frames, self.no_hand
        )
