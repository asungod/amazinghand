import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))

from link_monitor import AckMonitor, write_tracked  # noqa: E402
from protocol import StreamParser, decode_frame, encode_frame  # noqa: E402


class ProtocolTests(unittest.TestCase):
    def test_round_trip(self):
        frame = encode_frame("VISION", 7, 3, 320, 240, 80, 120, 96)
        message = decode_frame(frame)
        self.assertEqual(message["type"], "VISION")
        self.assertEqual(message["seq"], 7)
        self.assertEqual(message["args"], [3, 320, 240, 80, 120, 96])

    def test_train_round_trip(self):
        self.assertEqual(
            decode_frame(encode_frame("TRAIN", 8, 1)),
            {"type": "TRAIN", "seq": 8, "args": [1]},
        )

    def test_trainstat_round_trip(self):
        self.assertEqual(
            decode_frame(encode_frame("TRAINSTAT", 9, 1, 8, 3, 1, 4)),
            {"type": "TRAINSTAT", "seq": 9, "args": [1, 8, 3, 1, 4]},
        )

    def test_sign_round_trip_preserves_fixed_request_fields(self):
        self.assertEqual(
            decode_frame(encode_frame("SIGN", 10, 1, 1, 1)),
            {"type": "SIGN", "seq": 10, "args": [1, 1, 1]},
        )

    def test_signstat_round_trip_uses_max_eight_argument_budget(self):
        self.assertEqual(
            decode_frame(
                encode_frame("SIGNSTAT", 11, 1, 10, 1, 5, 0, 2, 1)
            ),
            {
                "type": "SIGNSTAT",
                "seq": 11,
                "args": [1, 10, 1, 5, 0, 2, 1],
            },
        )

    def test_aitrust_round_trip_preserves_four_uint32_fields(self):
        encoded = encode_frame("AITRUST", 12, 1, 1, 0, 250)
        self.assertEqual(encoded, b"$AITRUST,12,1,1,0,250*1EAA\r\n")
        self.assertEqual(
            decode_frame(encoded),
            {"type": "AITRUST", "seq": 12, "args": [1, 1, 0, 250]},
        )

    def test_fragmented_stream(self):
        parser = StreamParser()
        frame = encode_frame("PING", 9)
        self.assertEqual(parser.feed(frame[:3]), [])
        self.assertEqual(parser.feed(frame[3:8]), [])
        self.assertEqual(parser.feed(frame[8:]), [{"type": "PING", "seq": 9, "args": []}])

    def test_crc_error_is_dropped_and_next_frame_recovers(self):
        parser = StreamParser()
        broken = bytearray(encode_frame("PING", 1))
        broken[3] ^= 1
        result = parser.feed(bytes(broken) + encode_frame("PING", 2))
        self.assertEqual(result, [{"type": "PING", "seq": 2, "args": []}])

    def test_garbage_before_header_is_ignored(self):
        parser = StreamParser()
        result = parser.feed(b"boot log\r\nnoise" + encode_frame("ACK", 5, 0))
        self.assertEqual(result, [{"type": "ACK", "seq": 5, "args": [0]}])

    def test_oversized_unterminated_input_recovers(self):
        parser = StreamParser()
        parser.feed(b"$" + b"A" * 200)
        result = parser.feed(encode_frame("PING", 6))
        self.assertEqual(result, [{"type": "PING", "seq": 6, "args": []}])

    def test_new_header_recovers_unterminated_frame(self):
        parser = StreamParser()
        result = parser.feed(b"$VISION,1,broken" + encode_frame("PING", 8))
        self.assertEqual(result, [{"type": "PING", "seq": 8, "args": []}])

    def test_unsigned_ranges_are_enforced(self):
        for sequence in (-1, 65536):
            with self.subTest(sequence=sequence):
                with self.assertRaises(ValueError):
                    encode_frame("PING", sequence)
        for argument in (-1, 0x100000000):
            with self.subTest(argument=argument):
                with self.assertRaises(ValueError):
                    encode_frame("ACK", 1, argument)

    def test_unknown_type_and_too_many_args_are_rejected(self):
        with self.assertRaises(ValueError):
            encode_frame("UNKNOWN", 1)
        with self.assertRaises(ValueError):
            encode_frame("STATUS", 1, *range(9))


class AckMonitorTests(unittest.TestCase):
    @staticmethod
    def elapsed(now_ms, previous_ms):
        return now_ms - previous_ms

    def test_acknowledged_and_rejected_frames(self):
        monitor = AckMonitor(1000)
        monitor.record(1, "PING", 100)
        monitor.record(2, "VISION", 200)
        self.assertEqual(monitor.acknowledge(1, 0, 125, self.elapsed), "acked")
        self.assertEqual(monitor.acknowledge(2, 1, 275, self.elapsed), "rejected")
        self.assertEqual(monitor.acked, 1)
        self.assertEqual(monitor.rejected, 1)
        self.assertEqual(monitor.last_rtt_ms, 75)
        self.assertEqual(monitor.average_rtt_ms(), 50)
        self.assertEqual(monitor.max_rtt_ms, 75)
        self.assertEqual(len(monitor.pending), 0)

    def test_timeout_and_unexpected_ack_are_counted(self):
        monitor = AckMonitor(1000)
        monitor.record(7, "PING", 100)
        self.assertEqual(monitor.expire(1099, self.elapsed), [])
        self.assertEqual(monitor.expire(1100, self.elapsed), [(7, "PING")])
        self.assertEqual(
            monitor.acknowledge(7, 0, 1200, self.elapsed), "unexpected"
        )
        self.assertEqual(monitor.timed_out, 1)
        self.assertEqual(monitor.unexpected, 1)

    def test_ack_resets_consecutive_timeout_count(self):
        monitor = AckMonitor(1000)
        monitor.record(1, "PING", 0)
        monitor.record(2, "VISION", 0)
        monitor.expire(1000, self.elapsed)
        self.assertEqual(monitor.consecutive_timeouts, 2)
        self.assertEqual(monitor.max_consecutive_timeouts, 2)
        monitor.record(3, "PING", 1100)
        monitor.acknowledge(3, 0, 1120, self.elapsed)
        self.assertEqual(monitor.consecutive_timeouts, 0)
        self.assertEqual(monitor.max_consecutive_timeouts, 2)

    def test_full_write_is_tracked(self):
        class FullSerial:
            @staticmethod
            def write(frame):
                return len(frame)

        monitor = AckMonitor(1000)
        success, error_text = write_tracked(
            FullSerial(), b"frame", 4, "PING", 10, monitor
        )
        self.assertTrue(success)
        self.assertIsNone(error_text)
        self.assertIn(4, monitor.pending)
        self.assertEqual(monitor.send_failures, 0)

    def test_partial_and_exception_writes_are_not_tracked(self):
        class PartialSerial:
            @staticmethod
            def write(_frame):
                return 2

        class FailingSerial:
            @staticmethod
            def write(_frame):
                raise OSError("UART unavailable")

        monitor = AckMonitor(1000)
        partial = write_tracked(
            PartialSerial(), b"frame", 5, "PING", 10, monitor
        )
        failed = write_tracked(
            FailingSerial(), b"frame", 6, "PING", 20, monitor
        )
        self.assertFalse(partial[0])
        self.assertFalse(failed[0])
        self.assertEqual(monitor.send_failures, 2)
        self.assertEqual(monitor.pending, {})


if __name__ == "__main__":
    unittest.main()
