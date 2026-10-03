"""Mock and YOLO11 vision sources for the Smart Hand UART application."""


def format_replay_row(time_ms, payload):
    if type(time_ms) is not int or time_ms < 0:
        raise ValueError("time_ms must be a nonnegative integer")
    if payload is None:
        return "REPLAY,{},NONE,,,,,".format(time_ms)
    if not isinstance(payload, (tuple, list)) or len(payload) != 6:
        raise ValueError("payload must contain six fields")
    if any(type(value) is not int for value in payload):
        raise ValueError("payload fields must be integers")
    return "REPLAY,{},{},{},{},{},{},{}".format(time_ms, *payload)


def _normalized_payload(detection, frame_width, frame_height):
    if frame_width <= 0 or frame_height <= 0:
        raise ValueError("frame dimensions must be positive")

    try:
        class_id = int(detection["class_id"])
        x = int(detection["x"])
        y = int(detection["y"])
        width = int(detection["w"])
        height = int(detection["h"])
        score = float(detection["score"])
    except (KeyError, TypeError, ValueError):
        return None

    if class_id < 0 or class_id > 65535:
        return None
    if width <= 0 or height <= 0 or score < 0.0 or score > 1.0:
        return None
    if x >= frame_width or y >= frame_height or x + width <= 0 or y + height <= 0:
        return None

    left = max(0, min(x, frame_width - 1))
    top = max(0, min(y, frame_height - 1))
    right = max(0, min(x + width, frame_width))
    bottom = max(0, min(y + height, frame_height))
    if right <= left or bottom <= top:
        return None

    clipped_width = right - left
    clipped_height = bottom - top
    center_x = left + clipped_width // 2
    center_y = top + clipped_height // 2
    confidence = min(100, int(score * 100.0 + 0.5))
    return (
        class_id,
        center_x,
        center_y,
        clipped_width,
        clipped_height,
        confidence,
    )


def select_target(
    detections,
    frame_width,
    frame_height,
    allowed_class_ids=None,
    minimum_score=0.0,
):
    """Select highest-confidence detection, then prefer the larger box."""
    if minimum_score < 0.0 or minimum_score > 1.0:
        raise ValueError("minimum_score must be between 0 and 1")
    allowed = None if allowed_class_ids is None else set(allowed_class_ids)
    best_payload = None
    best_rank = None

    for detection in detections:
        payload = _normalized_payload(detection, frame_width, frame_height)
        if payload is None:
            continue
        class_id, _, _, width, height, confidence = payload
        if allowed is not None and class_id not in allowed:
            continue
        if confidence < int(minimum_score * 100.0 + 0.5):
            continue
        center_distance = abs(2 * payload[1] - frame_width) + abs(
            2 * payload[2] - frame_height
        )
        rank = (confidence, -center_distance, width * height)
        if best_rank is None or rank > best_rank:
            best_rank = rank
            best_payload = payload

    return best_payload


class MockVisionSource:
    def __init__(self, payload=(3, 320, 240, 80, 120, 96)):
        self.payload = payload
        self.frames = 0

    def read(self):
        self.frames += 1
        return self.payload

    def summary(self):
        return "mode=mock frames={} selected={}".format(self.frames, self.frames)


class DisabledVisionSource:
    def __init__(self, reason="configured"):
        self.reason = reason
        self.frames = 0

    def read(self):
        self.frames += 1
        return None

    def summary(self):
        return "mode=disabled frames={} reason={}".format(self.frames, self.reason)


class Yolo11VisionSource:
    def __init__(
        self,
        model_path,
        confidence_threshold=0.5,
        iou_threshold=0.45,
        allowed_class_ids=None,
    ):
        from maix import camera, nn, time

        self.detector = nn.YOLO11(model=model_path, dual_buff=True)
        self.frame_width = self.detector.input_width()
        self.frame_height = self.detector.input_height()
        self.camera = camera.Camera(
            self.frame_width,
            self.frame_height,
            self.detector.input_format(),
        )
        self.time = time
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = iou_threshold
        self.allowed_class_ids = allowed_class_ids
        self.frames = 0
        self.detections = 0
        self.selected = 0
        self.no_target = 0
        self.last_frame = None
        self.last_objects = []
        self.last_inference_ms = 0
        self.max_inference_ms = 0
        self.total_inference_ms = 0

    def average_inference_ms(self):
        if self.frames == 0:
            return 0
        return self.total_inference_ms // self.frames

    def inference_fps(self):
        average_ms = self.average_inference_ms()
        if average_ms <= 0:
            return 0
        return 1000 // average_ms

    def read(self):
        frame = self.camera.read()
        inference_start_ms = self.time.ticks_ms()
        objects = self.detector.detect(
            frame,
            conf_th=self.confidence_threshold,
            iou_th=self.iou_threshold,
        )
        inference_end_ms = self.time.ticks_ms()
        ticks_diff = getattr(self.time, "ticks_diff", None)
        if ticks_diff is None:
            inference_ms = inference_end_ms - inference_start_ms
        else:
            inference_ms = ticks_diff(inference_start_ms, inference_end_ms)
        inference_ms = max(0, inference_ms)
        self.last_inference_ms = inference_ms
        self.max_inference_ms = max(self.max_inference_ms, inference_ms)
        self.total_inference_ms += inference_ms
        self.last_frame = frame
        self.last_objects = objects
        self.frames += 1
        self.detections += len(objects)
        detections = [
            {
                "class_id": obj.class_id,
                "x": obj.x,
                "y": obj.y,
                "w": obj.w,
                "h": obj.h,
                "score": obj.score,
            }
            for obj in objects
        ]
        payload = select_target(
            detections,
            self.frame_width,
            self.frame_height,
            allowed_class_ids=self.allowed_class_ids,
            minimum_score=self.confidence_threshold,
        )
        if payload is None:
            self.no_target += 1
        else:
            self.selected += 1
        return payload

    def summary(self):
        return (
            "mode=yolo11 frames={} detections={} selected={} no_target={} "
            "infer_last_ms={} infer_avg_ms={} infer_max_ms={} infer_fps={}".format(
                self.frames,
                self.detections,
                self.selected,
                self.no_target,
                self.last_inference_ms,
                self.average_inference_ms(),
                self.max_inference_ms,
                self.inference_fps(),
            )
        )


def create_vision_source(
    mode,
    model_path,
    confidence_threshold,
    iou_threshold,
    allowed_class_ids,
):
    if mode == "mock":
        return MockVisionSource()
    if mode == "disabled":
        return DisabledVisionSource()
    if mode == "yolo11":
        return Yolo11VisionSource(
            model_path,
            confidence_threshold=confidence_threshold,
            iou_threshold=iou_threshold,
            allowed_class_ids=allowed_class_ids,
        )
    raise ValueError("unsupported VISION_MODE: {}".format(mode))
