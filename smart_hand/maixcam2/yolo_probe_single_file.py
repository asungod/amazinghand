"""Single-file MaixCAM2 YOLO11 probe for MaixVision 'Run File'."""

from maix import app, camera, display, image, nn, time


MODEL_PATH = "/root/models/yolo11n.mud"
CONFIDENCE_THRESHOLD = 0.5
IOU_THRESHOLD = 0.45
ALLOWED_CLASS_IDS = None
REPORT_INTERVAL_MS = 500
SHOW_PREVIEW = True


def elapsed_ms(now_ms, previous_ms):
    ticks_diff = getattr(time, "ticks_diff", None)
    if ticks_diff is not None:
        return ticks_diff(previous_ms, now_ms)
    return now_ms - previous_ms


def normalized_payload(obj, frame_width, frame_height):
    try:
        class_id = int(obj.class_id)
        x, y = int(obj.x), int(obj.y)
        width, height = int(obj.w), int(obj.h)
        score = float(obj.score)
    except (AttributeError, TypeError, ValueError):
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
    return (
        class_id,
        left + clipped_width // 2,
        top + clipped_height // 2,
        clipped_width,
        clipped_height,
        min(100, int(score * 100.0 + 0.5)),
    )


def select_target(objects, frame_width, frame_height):
    allowed = None if ALLOWED_CLASS_IDS is None else set(ALLOWED_CLASS_IDS)
    best_payload = None
    best_rank = None
    for obj in objects:
        payload = normalized_payload(obj, frame_width, frame_height)
        if payload is None:
            continue
        class_id, center_x, center_y, width, height, confidence = payload
        if allowed is not None and class_id not in allowed:
            continue
        center_distance = abs(2 * center_x - frame_width) + abs(2 * center_y - frame_height)
        rank = (confidence, -center_distance, width * height)
        if best_rank is None or rank > best_rank:
            best_rank = rank
            best_payload = payload
    return best_payload


def main():
    print("loading YOLO11 model:", MODEL_PATH)
    detector = nn.YOLO11(model=MODEL_PATH, dual_buff=True)
    frame_width = detector.input_width()
    frame_height = detector.input_height()
    print("model ready input={}x{} format={}".format(
        frame_width, frame_height, detector.input_format()))
    cam = camera.Camera(frame_width, frame_height, detector.input_format())
    screen = None
    if SHOW_PREVIEW:
        try:
            screen = display.Display()
        except Exception as exc:
            print("display init failed; console-only mode:", exc)

    frames = detections = selected = no_target = 0
    total_inference_ms = max_inference_ms = 0
    last_report_ms = None
    print("YOLO11 single-file probe started")
    while not app.need_exit():
        frame = cam.read()
        inference_start_ms = time.ticks_ms()
        objects = detector.detect(frame, conf_th=CONFIDENCE_THRESHOLD, iou_th=IOU_THRESHOLD)
        inference_end_ms = time.ticks_ms()
        inference_ms = max(0, elapsed_ms(inference_end_ms, inference_start_ms))
        frames += 1
        detections += len(objects)
        total_inference_ms += inference_ms
        max_inference_ms = max(max_inference_ms, inference_ms)
        average_ms = total_inference_ms // frames
        fps = 1000 // average_ms if average_ms > 0 else 0
        payload = select_target(objects, frame_width, frame_height)
        if payload is None:
            no_target += 1
        else:
            selected += 1

        if screen is not None:
            for obj in objects:
                frame.draw_rect(obj.x, obj.y, obj.w, obj.h, color=image.COLOR_RED)
                label = str(obj.class_id)
                if 0 <= obj.class_id < len(detector.labels):
                    label = detector.labels[obj.class_id]
                frame.draw_string(obj.x, obj.y, "{}: {:.2f}".format(label, obj.score),
                                  color=image.COLOR_RED)
            frame.draw_string(2, 2, "infer {} ms / {} fps".format(inference_ms, fps),
                              color=image.COLOR_RED)
            screen.show(frame)

        now_ms = time.ticks_ms()
        if last_report_ms is None or elapsed_ms(now_ms, last_report_ms) >= REPORT_INTERVAL_MS:
            if payload is None:
                print("target: NONE")
            else:
                print("target: class={} center=({},{}) size=({},{}) confidence={}".format(
                    *payload))
            print("vision stats: frames={} detections={} selected={} no_target={} "
                  "infer_last_ms={} infer_avg_ms={} infer_max_ms={} infer_fps={}".format(
                      frames, detections, selected, no_target, inference_ms, average_ms,
                      max_inference_ms, fps))
            last_report_ms = now_ms
        time.sleep_ms(10)


main()
