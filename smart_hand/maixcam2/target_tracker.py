"""Temporal stability and freshness tracking for VISION payloads."""


UINT32_MAX = 0xFFFFFFFF


def payload_iou(first, second):
    if first is None or second is None or first[0] != second[0]:
        return 0.0

    first_left = first[1] - first[3] / 2.0
    first_top = first[2] - first[4] / 2.0
    first_right = first_left + first[3]
    first_bottom = first_top + first[4]
    second_left = second[1] - second[3] / 2.0
    second_top = second[2] - second[4] / 2.0
    second_right = second_left + second[3]
    second_bottom = second_top + second[4]

    intersection_width = max(
        0.0, min(first_right, second_right) - max(first_left, second_left)
    )
    intersection_height = max(
        0.0, min(first_bottom, second_bottom) - max(first_top, second_top)
    )
    intersection = intersection_width * intersection_height
    union = first[3] * first[4] + second[3] * second[4] - intersection
    if union <= 0.0:
        return 0.0
    return intersection / union


class TargetTracker:
    def __init__(self, stable_frames, stale_timeout_ms, match_iou):
        if stable_frames <= 0:
            raise ValueError("stable_frames must be positive")
        if stale_timeout_ms <= 0:
            raise ValueError("stale_timeout_ms must be positive")
        if match_iou < 0.0 or match_iou > 1.0:
            raise ValueError("match_iou must be between 0 and 1")
        self.stable_frames = stable_frames
        self.stale_timeout_ms = stale_timeout_ms
        self.match_iou = match_iou
        self.candidate = None
        self.candidate_frames = 0
        self.active = None
        self.active_seen_ms = None
        self.observations = 0
        self.empty_observations = 0
        self.invalid_observations = 0
        self.acquired = 0
        self.updated = 0
        self.switches = 0
        self.lost = 0

    @staticmethod
    def _valid(payload):
        if not isinstance(payload, (tuple, list)) or len(payload) != 6:
            return False
        if any(type(value) is not int for value in payload):
            return False
        class_id, center_x, center_y, width, height, confidence = payload
        return (
            0 <= class_id <= 65535
            and 0 <= center_x <= UINT32_MAX
            and 0 <= center_y <= UINT32_MAX
            and 0 < width <= UINT32_MAX
            and 0 < height <= UINT32_MAX
            and 0 <= confidence <= 100
        )

    def _matches(self, first, second):
        return first[0] == second[0] and payload_iou(first, second) >= self.match_iou

    def _clear_candidate(self):
        self.candidate = None
        self.candidate_frames = 0

    def observe(self, payload, now_ms, elapsed_ms):
        self.observations += 1
        if payload is None:
            self.empty_observations += 1
            self._clear_candidate()
            return self.current(now_ms, elapsed_ms)
        if not self._valid(payload):
            self.invalid_observations += 1
            self._clear_candidate()
            return self.current(now_ms, elapsed_ms)
        payload = tuple(payload)

        if self.active is not None and self._matches(self.active, payload):
            self.active = payload
            self.active_seen_ms = now_ms
            self.updated += 1
            self._clear_candidate()
            return self.active

        if self.candidate is not None and self._matches(self.candidate, payload):
            self.candidate = payload
            self.candidate_frames += 1
        else:
            self.candidate = payload
            self.candidate_frames = 1

        if self.candidate_frames >= self.stable_frames:
            if self.active is None:
                self.acquired += 1
            else:
                self.switches += 1
            self.active = self.candidate
            self.active_seen_ms = now_ms
            self._clear_candidate()
        return self.current(now_ms, elapsed_ms)

    def current(self, now_ms, elapsed_ms):
        if (
            self.active is not None
            and elapsed_ms(now_ms, self.active_seen_ms) > self.stale_timeout_ms
        ):
            self.active = None
            self.active_seen_ms = None
            self.lost += 1
        return self.active

    def summary(self):
        return (
            "observations={} empty={} invalid={} acquired={} updated={} "
            "switches={} lost={} candidate_frames={} active={}".format(
                self.observations,
                self.empty_observations,
                self.invalid_observations,
                self.acquired,
                self.updated,
                self.switches,
                self.lost,
                self.candidate_frames,
                1 if self.active is not None else 0,
            )
        )


class VisionScheduler:
    """Coordinate vision processing and rate-limited VISION transmission."""

    def __init__(self, tracker, process_interval_ms, send_interval_ms):
        if process_interval_ms < 0:
            raise ValueError("process_interval_ms must not be negative")
        if send_interval_ms <= 0:
            raise ValueError("send_interval_ms must be positive")
        self.tracker = tracker
        self.process_interval_ms = process_interval_ms
        self.send_interval_ms = send_interval_ms
        self.last_process_ms = None
        self.last_send_ms = None

    def process_due(self, now_ms, elapsed_ms):
        return (
            self.process_interval_ms == 0
            or self.last_process_ms is None
            or elapsed_ms(now_ms, self.last_process_ms)
            >= self.process_interval_ms
        )

    def observe(self, payload, now_ms, elapsed_ms):
        result = self.tracker.observe(payload, now_ms, elapsed_ms)
        self.last_process_ms = now_ms
        return result

    def take_send_payload(self, now_ms, elapsed_ms):
        if (
            self.last_send_ms is not None
            and elapsed_ms(now_ms, self.last_send_ms) < self.send_interval_ms
        ):
            return None
        self.last_send_ms = now_ms
        return self.tracker.current(now_ms, elapsed_ms)
