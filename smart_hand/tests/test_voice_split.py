"""Speaker-disjoint split contract for the Titan keyword-spotting corpus.

Why this module exists
----------------------
One person recording 20 takes of the same word, in the same room, on the same
microphone, at the same distance, produces 20 highly correlated samples. If the
train/validation split is drawn over sample indices, the validation set is
mostly made of people the model already memorised, the validation number looks
excellent, and the model collapses the first time a stranger speaks to the
device. The party trick that hides the bug is that nothing about the training
run looks wrong.

So the split is made over speaker identities, and this module pins that down:

    train / validation speakers are disjoint              (always)
    test speakers exist only with >= 3 speakers           (never faked)
    every take of a speaker lands in exactly one split    (anti-leakage)
    a corpus with one speaker is refused, not resampled  (SystemExit)
    a file name that does not carry a speaker is an error (no silent default)

Runs on a plain interpreter: train_voice_kws imports TensorFlow inside its
functions only, so importing it here costs nothing and needs no GPU, no TFLite
and no soundfile.

    python -m unittest smart_hand.tests.test_voice_split -v
"""

from __future__ import annotations

import sys
import types
import unittest
import wave
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AI_DIR = PROJECT_ROOT / "titan_ai" / "voice"
sys.path.insert(0, str(AI_DIR))

import train_voice_kws as tvk  # noqa: E402

SEED = 7


def per_sample_speakers(counts: dict) -> list:
    """{speaker: n_takes} -> the per-sample speaker list a corpus would give."""
    listeners = []
    for speaker, takes in counts.items():
        listeners.extend([speaker] * takes)
    return listeners


def interleaved_speakers(plan: dict) -> list:
    """Round-robin the takes so one speaker's samples are non-contiguous.

    Contiguity would make an index-order bug (e.g. slicing `speakers` instead of
    grouping it) invisible; interleaving forces the implementation to actually
    group by identity.
    """
    queues = {speaker: takes for speaker, takes in plan.items()}
    out = []
    while any(queues.values()):
        for speaker in list(queues):
            if queues[speaker]:
                out.append(speaker)
                queues[speaker] -= 1
    return out


def indices_of(speakers: list, wanted: str) -> set:
    return {i for i, s in enumerate(speakers) if s == wanted}


class SpeakerSplitTwoSpeakerTests(unittest.TestCase):
    """Two speakers is the smallest corpus that can be split honestly."""

    def setUp(self):
        self.speakers = per_sample_speakers({"spk01": 30, "spk02": 20})
        self.train_idx, self.val_idx, self.test_idx, self.info = tvk.speaker_split(
            self.speakers, seed=SEED
        )

    def test_train_and_validation_speakers_are_disjoint(self):
        self.assertEqual(set(self.info["train_speakers"]) & set(self.info["val_speakers"]), set())
        self.assertEqual(
            sorted(set(self.info["train_speakers"]) | set(self.info["val_speakers"])),
            ["spk01", "spk02"],
        )

    def test_no_independent_test_set_is_invented(self):
        """The validation set must not be relabelled as a test set."""
        self.assertEqual(len(self.test_idx), 0)
        self.assertEqual(self.info["test_speakers"], [])
        self.assertFalse(self.info["has_independent_test_speakers"])
        self.assertIn("无独立测试说话人", self.info["note"])
        self.assertIn("不以验证集冒充测试集", self.info["note"])

    def test_info_reports_speaker_disjoint(self):
        self.assertIs(self.info["speaker_disjoint"], True)
        self.assertEqual(self.info["split_scheme"], "speaker_disjoint")

    def test_sample_counts_and_speaker_lists_are_reported(self):
        self.assertEqual(self.info["train_samples"], len(self.train_idx))
        self.assertEqual(self.info["val_samples"], len(self.val_idx))
        self.assertEqual(
            len(self.train_idx) + len(self.val_idx) + len(self.test_idx),
            len(self.speakers),
        )
        for key in ("train_speakers", "val_speakers", "test_speakers"):
            self.assertIn(key, self.info)

    def test_whole_speakers_are_held_out_together(self):
        held_out = set(self.info["test_speakers"]) | set(self.info["val_speakers"])
        for speaker in held_out:
            self.assertFalse(
                indices_of(self.speakers, speaker) & set(self.train_idx.tolist()),
                f"{speaker} appears in both training and validation",
            )


class SpeakerSplitThreeOrMoreTests(unittest.TestCase):
    """With >= 3 speakers there is a real, speaker-disjoint test set."""

    PLAN = {"spk01": 24, "spk02": 18, "spk03": 31, "spk04": 12, "spk05": 20}

    def setUp(self):
        self.speakers = interleaved_speakers(self.PLAN)
        self.train_idx, self.val_idx, self.test_idx, self.info = tvk.speaker_split(
            self.speakers, seed=SEED
        )

    def test_three_splits_are_pairwise_disjoint(self):
        train = set(self.info["train_speakers"])
        val = set(self.info["val_speakers"])
        test = set(self.info["test_speakers"])
        self.assertEqual(train & val, set())
        self.assertEqual(train & test, set())
        self.assertEqual(val & test, set())
        self.assertEqual(train | val | test, set(self.PLAN))

    def test_every_split_is_non_empty(self):
        self.assertTrue(self.info["train_speakers"])
        self.assertTrue(self.info["val_speakers"])
        self.assertTrue(self.info["test_speakers"])
        self.assertGreater(len(self.train_idx), 0)
        self.assertGreater(len(self.val_idx), 0)
        self.assertGreater(len(self.test_idx), 0)
        self.assertTrue(self.info["has_independent_test_speakers"])

    def test_each_speaker_lands_entirely_in_one_split(self):
        """The anti-leakage assertion: no speaker may straddle two splits."""
        held = {
            "train": set(self.train_idx.tolist()),
            "val": set(self.val_idx.tolist()),
            "test": set(self.test_idx.tolist()),
        }
        for speaker in self.PLAN:
            owners = [
                name for name, assignment in held.items()
                if indices_of(self.speakers, speaker) & assignment
            ]
            self.assertEqual(
                len(owners), 1,
                f"{speaker}'s takes are spread across {owners}; that leaks the "
                f"speaker into more than one split",
            )
            self.assertTrue(indices_of(self.speakers, speaker) <= held[owners[0]])

    def test_no_sample_is_dropped_or_duplicated(self):
        all_idx = np.concatenate([self.train_idx, self.val_idx, self.test_idx])
        self.assertEqual(all_idx.size, len(self.speakers))
        self.assertEqual(sorted(all_idx.tolist()), list(range(len(self.speakers))))

    def test_split_is_deterministic_for_a_seed(self):
        again = tvk.speaker_split(self.speakers, seed=SEED)
        self.assertEqual(sorted(again[0].tolist()), sorted(self.train_idx.tolist()))
        self.assertEqual(sorted(again[1].tolist()), sorted(self.val_idx.tolist()))
        self.assertEqual(sorted(again[2].tolist()), sorted(self.test_idx.tolist()))


class SpeakerSplitRefusesTooFewSpeakers(unittest.TestCase):
    def test_single_speaker_raises_system_exit(self):
        with self.assertRaises(SystemExit) as ctx:
            tvk.speaker_split(per_sample_speakers({"spk01": 40}), seed=SEED)
        message = str(ctx.exception)
        self.assertIn("拒绝训练", message)
        self.assertIn("spk01", message)

    def test_message_tells_the_operator_what_to_do(self):
        with self.assertRaises(SystemExit) as ctx:
            tvk.speaker_split(["spk01", "spk01", "spk01"], seed=SEED)
        message = str(ctx.exception)
        self.assertIn("tools/voice_dataset/README.md", message)
        self.assertIn("--synthetic", message)

    def test_empty_corpus_raises_system_exit(self):
        with self.assertRaises(SystemExit):
            tvk.speaker_split([], seed=SEED)


class SpeakerFilenameTests(unittest.TestCase):
    def test_parses_speaker_from_the_recorded_name(self):
        self.assertEqual(tvk.parse_speaker("spk01_near_003.wav"), "spk01")
        self.assertEqual(tvk.parse_speaker("spk02_mid_7.wav"), "spk02")
        self.assertEqual(tvk.parse_speaker("spk03_far_12.wav"), "spk03")
        self.assertEqual(
            tvk.parse_speaker(Path("D:/voice_dataset/开始训练/spk04_near_001.wav")),
            "spk04",
        )

    def test_malformed_names_raise_instead_of_defaulting(self):
        malformed = [
            "spk01.wav",              # no distance/index fields at all
            "spk01_near.wav",         # missing index
            "spk01_near_003_04.wav",  # too many fields
            "_near_003.wav",          # empty speaker
            "spk01__003.wav",         # empty distance
            "spk01_near_abc.wav",     # non-numeric index
            "spk01_near_003",         # wrong extension
            "near_003.wav",           # only two fields
            "spk01_near_003.txt",
        ]
        for name in malformed:
            with self.subTest(name=name):
                with self.assertRaises(ValueError) as ctx:
                    tvk.parse_speaker(name)
                self.assertIn(name, str(ctx.exception))
                self.assertIn("spk01_near_003.wav", str(ctx.exception))

    def test_wav_corpus_threads_speakers_and_refuses_bad_names(self):
        """End-to-end over the loader, with soundfile stubbed by the stdlib.

        The point is that a badly named take stops training instead of being
        quietly attributed to some default speaker.
        """
        import tempfile

        real_soundfile = sys.modules.get("soundfile")
        sys.modules["soundfile"] = _stub_soundfile()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                # 求助 carries both speakers; every other class gets one valid
                # take so the loader has a full six-class directory to walk.
                for label in tvk.LABELS:
                    _write_wav(root / label / "spk01_near_001.wav")
                _write_wav(root / "求助" / "spk02_far_002.wav")

                pcm, y, speakers = tvk.wav_corpus(root)
                self.assertEqual(len(speakers), len(y))
                self.assertEqual(pcm.shape[0], len(speakers))
                self.assertEqual(
                    sorted(set(speakers)), ["spk01", "spk02"],
                )

                # The loader's output must feed the splitter directly: no dtype
                # or shape surprise between "what the directory gave us" and
                # "what the splitter expects".
                train_idx, val_idx, test_idx, info = tvk.speaker_split(speakers, seed=SEED)
                self.assertIs(info["speaker_disjoint"], True)
                self.assertEqual(sorted(np.concatenate(
                    [train_idx, val_idx, test_idx]).tolist()), list(range(len(y))))
                self.assertEqual(len(test_idx), 0)

                _write_wav(root / "求助" / "spk03noidx.wav")
                with self.assertRaises(SystemExit) as ctx:
                    tvk.wav_corpus(root)
                self.assertIn("spk03noidx.wav", str(ctx.exception))
                self.assertIn("spk01_near_003.wav", str(ctx.exception))
        finally:
            if real_soundfile is None:
                sys.modules.pop("soundfile", None)
            else:
                sys.modules["soundfile"] = real_soundfile


def _write_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = np.zeros(tvk.fe.WINDOW_SAMPLES, dtype=np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(tvk.fe.SAMPLE_RATE_HZ)
        handle.writeframes(frames.tobytes())


def _stub_soundfile() -> types.ModuleType:
    """Minimal `sf.read(path, dtype=...)` -> (int16 mono array, rate)."""
    module = types.ModuleType("soundfile")

    def read(path, dtype="int16", always_2d=False):
        with wave.open(str(path), "rb") as handle:
            rate = handle.getframerate()
            data = np.frombuffer(
                handle.readframes(handle.getnframes()), dtype=np.int16
            ).copy()
        return data, rate

    module.read = read
    return module


class SyntheticSelftestIsNotASpeakerSplit(unittest.TestCase):
    """The self-test path must not masquerade as a speaker-disjoint split."""

    def test_synthetic_info_declares_itself_not_speaker_disjoint(self):
        train_idx, val_idx, test_idx, info = tvk.synthetic_split(600, seed=SEED)
        self.assertIs(info["speaker_disjoint"], False)
        self.assertEqual(info["split_scheme"], "random_by_sample_synthetic_selftest")
        self.assertIsNone(info["train_speakers"])
        self.assertEqual(len(test_idx), 0)
        self.assertFalse(info["has_independent_test_speakers"])

    def test_synthetic_split_covers_every_sample_once(self):
        train_idx, val_idx, test_idx, _ = tvk.synthetic_split(600, seed=SEED)
        all_idx = np.concatenate([train_idx, val_idx, test_idx])
        self.assertEqual(sorted(all_idx.tolist()), list(range(600)))


METRICS_PATH = AI_DIR / "generated" / "voice_training_metrics.json"


@unittest.skipUnless(METRICS_PATH.exists(), "run train_voice_kws.py first")
class TrainingMetricsHonestyTests(unittest.TestCase):
    """Whatever produced the shipped artifact, it must not over-claim.

    Reads the metrics on disk rather than training: the artifact is the thing
    other people read, so the contract has to hold for it, not just for a run
    this test triggers.
    """

    @classmethod
    def setUpClass(cls):
        import json

        cls.metrics = json.loads(METRICS_PATH.read_text(encoding="utf-8"))

    def test_split_kind_is_recorded(self):
        for key in ("corpus_kind", "is_real_corpus", "split_is_speaker_disjoint", "split"):
            self.assertIn(key, self.metrics, f"metrics are stale: missing {key}")
        self.assertIsInstance(self.metrics["is_real_corpus"], bool)
        self.assertIsInstance(self.metrics["split_is_speaker_disjoint"], bool)

    def test_synthetic_metrics_deny_being_an_accuracy(self):
        if self.metrics["is_real_corpus"]:
            self.skipTest("shipped artifact came from real recordings")
        self.assertFalse(
            self.metrics["accuracy_interpretable_as_keyword_spotting"],
            "a synthetic self-test must never publish an interpretable accuracy",
        )
        self.assertTrue(
            self.metrics["accuracy_interpretation_note"].strip(),
            "the denial must carry its reason",
        )
        self.assertFalse(self.metrics["split_is_speaker_disjoint"])

    def test_real_corpus_without_test_speakers_denies_being_an_accuracy(self):
        if not self.metrics["is_real_corpus"]:
            self.skipTest("shipped artifact came from the synthetic self-test")
        if not self.metrics["split"]["has_independent_test_speakers"]:
            self.assertFalse(
                self.metrics["accuracy_interpretable_as_keyword_spotting"])

    def test_field_validation_flags_stay_false(self):
        self.assertFalse(self.metrics["field_accuracy_validated"])
        self.assertFalse(self.metrics["hardware_inference_validated"])
        self.assertFalse(self.metrics["controls_servo"])


if __name__ == "__main__":
    unittest.main()
