import random
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))

from protocol import MAX_FRAME_SIZE, StreamParser, encode_frame  # noqa: E402


class ProtocolStressTests(unittest.TestCase):
    def test_random_chunk_boundaries_preserve_all_frames(self):
        rng = random.Random(0x5A17)
        expected_sequences = list(range(200))
        stream = b"".join(
            encode_frame("PING", sequence)
            if sequence % 2 == 0
            else encode_frame("VISION", sequence, 3, 320, 240, 80, 120, 96)
            for sequence in expected_sequences
        )

        parser = StreamParser()
        parsed = []
        offset = 0
        while offset < len(stream):
            chunk_size = rng.randint(1, 31)
            parsed.extend(parser.feed(stream[offset : offset + chunk_size]))
            offset += chunk_size

        self.assertEqual(
            [message["seq"] for message in parsed], expected_sequences
        )

    def test_random_noise_and_corruption_recover_to_valid_frame(self):
        rng = random.Random(0xC0DE)
        for sequence in range(200):
            parser = StreamParser()
            noise = bytes(rng.getrandbits(8) for _ in range(rng.randint(0, 300)))
            broken = bytearray(encode_frame("VISION", 1, 2, 100, 100, 30, 40, 88))
            broken[8] ^= 0x01
            valid = encode_frame("PING", sequence)
            parsed = parser.feed(noise + bytes(broken) + valid)
            self.assertTrue(parsed)
            self.assertEqual(parsed[-1], {"type": "PING", "seq": sequence, "args": []})

    def test_oversized_unterminated_chunk_does_not_remain_buffered(self):
        parser = StreamParser()
        parser.feed(b"$" + b"X" * 10000)
        self.assertLessEqual(len(parser._buffer), MAX_FRAME_SIZE)
        self.assertEqual(
            parser.feed(encode_frame("PING", 77)),
            [{"type": "PING", "seq": 77, "args": []}],
        )


if __name__ == "__main__":
    unittest.main()
