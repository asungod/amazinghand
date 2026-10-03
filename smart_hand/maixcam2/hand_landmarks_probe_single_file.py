"""Single-file MaixCAM2 rehabilitation probe; no UART and no motion."""

import math

from maix import app, camera, display, image, nn


MODEL_PATH = "/root/models/hand_landmarks.mud"
OPEN_THRESHOLD = 0.88
CLOSED_THRESHOLD = 0.72


def _distance(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def hand_openness(raw_points):
    if len(raw_points) != 63:
        raise ValueError("expected 63 xyz landmark values")
    points = [
        (float(raw_points[index]), float(raw_points[index + 1]))
        for index in range(0, 63, 3)
    ]
    scores = []
    for mcp, pip, dip, tip in (
        (5, 6, 7, 8),
        (9, 10, 11, 12),
        (13, 14, 15, 16),
        (17, 18, 19, 20),
    ):
        path = (
            _distance(points[mcp], points[pip])
            + _distance(points[pip], points[dip])
            + _distance(points[dip], points[tip])
        )
        if path <= 1e-6:
            raise ValueError("degenerate finger landmarks")
        scores.append(max(0.0, min(1.0, _distance(points[mcp], points[tip]) / path)))
    return sum(scores) / len(scores)


def classify_openness(score):
    if score >= OPEN_THRESHOLD:
        return "OPEN"
    if score <= CLOSED_THRESHOLD:
        return "CLOSED"
    return "MID"


class RepetitionTracker:
    def __init__(self, stable_frames=3):
        self.stable_frames = stable_frames
        self.phase = "WAIT_OPEN"
        self.repetitions = 0
        self.candidate = None
        self.candidate_frames = 0

    def observe(self, posture):
        if posture in (None, "MID"):
            self.candidate = None
            self.candidate_frames = 0
            return False
        if posture != self.candidate:
            self.candidate = posture
            self.candidate_frames = 1
        else:
            self.candidate_frames += 1
        if self.candidate_frames < self.stable_frames:
            return False

        completed = False
        if self.phase == "WAIT_OPEN" and posture == "OPEN":
            self.phase = "WAIT_CLOSE"
        elif self.phase == "WAIT_CLOSE" and posture == "CLOSED":
            self.phase = "WAIT_REOPEN"
        elif self.phase == "WAIT_REOPEN" and posture == "OPEN":
            self.repetitions += 1
            self.phase = "WAIT_CLOSE"
            completed = True
        self.candidate_frames = 0
        return completed


def main():
    detector = nn.HandLandmarks(model=MODEL_PATH)
    cam = camera.Camera(320, 224, detector.input_format())
    screen = display.Display()
    tracker = RepetitionTracker(stable_frames=3)
    print("HAND REHAB PROBE: vision only; uart_opened=false; motion=false")

    while not app.need_exit():
        frame = cam.read()
        objects = detector.detect(frame, conf_th=0.7, iou_th=0.45, conf_th2=0.8)
        if objects:
            hand = max(objects, key=lambda obj: obj.w * obj.h)
            landmarks = hand.points[8 : 8 + 63]
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
