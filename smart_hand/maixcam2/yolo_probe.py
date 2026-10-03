"""Run camera and YOLO11 target selection without Titan or UART wiring."""

from maix import app, display, image, time

from vision_source import Yolo11VisionSource, format_replay_row


MODEL_PATH = "/root/models/yolo11n.mud"
CONFIDENCE_THRESHOLD = 0.5
IOU_THRESHOLD = 0.45
ALLOWED_CLASS_IDS = None  # Example graspable COCO IDs: (39, 41, 47, 49, 65)
REPORT_INTERVAL_MS = 500
SHOW_PREVIEW = True
PRINT_REPLAY_ROWS = False


def elapsed_ms(now_ms, previous_ms):
    ticks_diff = getattr(time, "ticks_diff", None)
    if ticks_diff is not None:
        return ticks_diff(previous_ms, now_ms)
    return now_ms - previous_ms


def main():
    source = Yolo11VisionSource(
        MODEL_PATH,
        confidence_threshold=CONFIDENCE_THRESHOLD,
        iou_threshold=IOU_THRESHOLD,
        allowed_class_ids=ALLOWED_CLASS_IDS,
    )
    screen = None
    if SHOW_PREVIEW:
        try:
            screen = display.Display()
        except Exception as exc:
            print("display init failed; console-only mode:", exc)
    last_report_ms = None
    start_ms = time.ticks_ms()
    print("YOLO11 probe started with", MODEL_PATH)
    if PRINT_REPLAY_ROWS:
        print("REPLAY,time_ms,class_id,center_x,center_y,width,height,confidence")

    while not app.need_exit():
        payload = source.read()
        if screen is not None:
            frame = source.last_frame
            for obj in source.last_objects:
                frame.draw_rect(obj.x, obj.y, obj.w, obj.h, color=image.COLOR_RED)
                label = str(obj.class_id)
                if 0 <= obj.class_id < len(source.detector.labels):
                    label = source.detector.labels[obj.class_id]
                frame.draw_string(
                    obj.x,
                    obj.y,
                    "{}: {:.2f}".format(label, obj.score),
                    color=image.COLOR_RED,
                )
            frame.draw_string(
                2,
                2,
                "infer {} ms / {} fps".format(
                    source.last_inference_ms, source.inference_fps()
                ),
                color=image.COLOR_RED,
            )
            screen.show(frame)
        now_ms = time.ticks_ms()
        if PRINT_REPLAY_ROWS:
            replay_time_ms = max(0, elapsed_ms(now_ms, start_ms))
            print(format_replay_row(replay_time_ms, payload))
        if (
            last_report_ms is None
            or elapsed_ms(now_ms, last_report_ms) >= REPORT_INTERVAL_MS
        ):
            if payload is None:
                print("target: NONE")
            else:
                print(
                    "target: class={} center=({},{}) size=({},{}) confidence={}".format(
                        *payload
                    )
                )
            print("vision stats:", source.summary())
            last_report_ms = now_ms
        time.sleep_ms(10)


if __name__ == "__main__":
    main()
