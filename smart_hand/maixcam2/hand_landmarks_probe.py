"""MaixCAM2 hand-rehabilitation vision probe; never opens UART or moves servos."""

from maix import app, camera, display, image, nn

from hand_rehab_tracker import RepetitionTracker, classify_openness, hand_openness

MODEL_PATH = "/root/models/hand_landmarks.mud"
CONFIDENCE = 0.7
IOU = 0.45
LANDMARK_CONFIDENCE = 0.8


def main():
    detector = nn.HandLandmarks(model=MODEL_PATH)
    cam = camera.Camera(320, 224, detector.input_format())
    screen = display.Display()
    tracker = RepetitionTracker(stable_frames=3)
    print("HAND REHAB PROBE: vision only; uart_opened=false; motion=false")

    while not app.need_exit():
        frame = cam.read()
        objects = detector.detect(
            frame,
            conf_th=CONFIDENCE,
            iou_th=IOU,
            conf_th2=LANDMARK_CONFIDENCE,
        )
        if objects:
            hand = max(objects, key=lambda obj: obj.w * obj.h)
            landmarks = hand.points[8 : 8 + 21 * 3]
            score = hand_openness(landmarks)
            posture = classify_openness(score)
            if tracker.observe(posture):
                print("USER REPETITION {} COMPLETE".format(tracker.repetitions))
            detector.draw_hand(frame, hand.class_id, hand.points, 4, 10, box=True)
            frame.draw_string(
                4,
                4,
                "HAND {} score={:.2f} REP={} {}".format(
                    posture, score, tracker.repetitions, tracker.phase
                ),
                color=image.COLOR_RED,
            )
        else:
            tracker.observe(None)
            frame.draw_string(4, 4, "HAND NOT FOUND", color=image.COLOR_RED)
        screen.show(frame)


if __name__ == "__main__":
    main()
