"""ACK accounting for the MaixCAM2-to-Titan UART link."""


class AckMonitor:
    def __init__(self, timeout_ms):
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        self.timeout_ms = timeout_ms
        self.pending = {}
        self.sent = 0
        self.acked = 0
        self.rejected = 0
        self.unexpected = 0
        self.malformed = 0
        self.timed_out = 0
        self.send_failures = 0
        self.consecutive_timeouts = 0
        self.max_consecutive_timeouts = 0
        self.last_rtt_ms = None
        self.max_rtt_ms = 0
        self.total_rtt_ms = 0
        self.rtt_samples = 0

    def record(self, sequence, message_type, sent_ms):
        self.pending[sequence] = (message_type, sent_ms)
        self.sent += 1

    def acknowledge(self, sequence, status, now_ms, elapsed_ms):
        pending = self.pending.pop(sequence, None)
        if pending is None:
            self.unexpected += 1
            return "unexpected"
        _, sent_ms = pending
        rtt_ms = elapsed_ms(now_ms, sent_ms)
        if rtt_ms >= 0:
            self.last_rtt_ms = rtt_ms
            self.max_rtt_ms = max(self.max_rtt_ms, rtt_ms)
            self.total_rtt_ms += rtt_ms
            self.rtt_samples += 1
        self.consecutive_timeouts = 0
        if status == 0:
            self.acked += 1
            return "acked"
        self.rejected += 1
        return "rejected"

    def note_malformed(self):
        self.malformed += 1

    def note_send_failure(self):
        self.send_failures += 1

    def expire(self, now_ms, elapsed_ms):
        expired = []
        for sequence, (message_type, sent_ms) in list(self.pending.items()):
            if elapsed_ms(now_ms, sent_ms) >= self.timeout_ms:
                expired.append((sequence, message_type))
                del self.pending[sequence]
        self.timed_out += len(expired)
        self.consecutive_timeouts += len(expired)
        self.max_consecutive_timeouts = max(
            self.max_consecutive_timeouts, self.consecutive_timeouts
        )
        return expired

    def average_rtt_ms(self):
        if self.rtt_samples == 0:
            return 0
        return self.total_rtt_ms // self.rtt_samples

    def summary(self):
        return (
            "sent={} tx_fail={} acked={} rejected={} unexpected={} malformed={} "
            "timeout={} consecutive_timeout={} max_consecutive_timeout={} "
            "pending={} rtt_last_ms={} rtt_avg_ms={} rtt_max_ms={}".format(
                self.sent,
                self.send_failures,
                self.acked,
                self.rejected,
                self.unexpected,
                self.malformed,
                self.timed_out,
                self.consecutive_timeouts,
                self.max_consecutive_timeouts,
                len(self.pending),
                self.last_rtt_ms if self.last_rtt_ms is not None else -1,
                self.average_rtt_ms(),
                self.max_rtt_ms,
            )
        )


def write_tracked(serial, frame, sequence, message_type, sent_ms, monitor):
    """Write one complete frame and track it only after a full UART write."""
    try:
        written = serial.write(frame)
    except Exception as exc:
        monitor.note_send_failure()
        return False, "exception: {}".format(exc)
    if written != len(frame):
        monitor.note_send_failure()
        return False, "wrote {} of {} bytes".format(written, len(frame))
    monitor.record(sequence, message_type, sent_ms)
    return True, None
