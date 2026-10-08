"""Sequence state regressions using synthetic observations, no device claims."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "maixcam2"))
from sign_sequence import SEQUENCES, SignSequenceTracker, motion_evidence
from sign_lesson import SignLessonController
from gesture_classifier import classify_gesture
from smart_hand.tests.test_gesture_palm_direction import palm_shape


def observation(phase):
    evidence = {"finger_extension": [0.2]*4, "thumb_extension": 0.2,
                "thumb_angle_deg": 110, "index_angle_deg": 110,
                "thumb_tip_distance": 0.8, "index_lateral": 0.0, "thumb_inside": False}
    result = {"gesture_id": "UNKNOWN", "confidence": 0.1, "stable_ms": 100000,
              "valid": False, "error_code": "LOW_CONFIDENCE", "motion_evidence": evidence}
    if phase.startswith("shape:"):
        result.update(gesture_id=phase[6:], confidence=0.95, valid=True, error_code="OK")
    elif phase == "thumb_open":
        evidence.update(thumb_extension=0.8, thumb_angle_deg=170)
    elif phase == "index_open" or phase.startswith("point_"):
        evidence.update(finger_extension=[0.95, 0.2, 0.2, 0.2], index_angle_deg=170)
        if phase == "point_side":
            evidence["index_lateral"] = 0.5
        elif phase == "point_other":
            evidence["index_lateral"] = -0.5
    elif phase == "index_bend":
        evidence["finger_extension"][0] = 0.75
    elif phase == "palm_open":
        evidence.update(finger_extension=[0.95]*4, thumb_extension=0.8, thumb_angle_deg=170)
    elif phase == "thumb_in":
        evidence.update(finger_extension=[0.95]*4, thumb_inside=True)
    elif phase == "help_close":
        evidence.update(thumb_inside=True)
    return result


def hold(tracker, result, now):
    # Final stage requires 300 ms; no gaps >500 ms; at least two reads.
    tracker.observe(result, now)
    tracker.observe(result, now+150)
    tracker.observe(result, now+320)
    return now+400


class SignSequenceTests(unittest.TestCase):
    def help_final_tracker(self):
        tracker = SignSequenceTracker("signal_help")
        now = hold(tracker, observation("palm_open"), 0)
        now = hold(tracker, observation("thumb_in"), now)
        self.assertEqual(tracker.index, 2)
        return tracker, now

    def test_hidden_thumb_never_automatically_passes_even_with_favourable_label(self):
        for label in ("FIST", "THUMBS_UP", "UNKNOWN", "OPEN_PALM"):
            with self.subTest(label=label):
                tracker, now = self.help_final_tracker()
                result = observation("help_close")
                result["gesture_id"] = label
                hold(tracker, result, now)
                self.assertFalse(tracker.snapshot()["complete"])
                self.assertEqual(tracker.index, 2)
                self.assertIn("人工复核", tracker.snapshot()["instruction"])

    def test_help_close_rejects_open_fingers_or_thumb_outside_or_far(self):
        for field, value in (("finger_extension", [0.95]*4),
                             ("finger_extension", [0.2, 0.2, 0.7, 0.2]),
                             ("thumb_inside", False), ("thumb_tip_distance", 1.16)):
            with self.subTest(field=field, value=value):
                tracker, now = self.help_final_tracker()
                result = observation("help_close")
                result.update(gesture_id="FIST", confidence=.99, valid=True, error_code="OK")
                result["motion_evidence"][field] = value
                hold(tracker, result, now)
                self.assertEqual(tracker.index, 2)
                self.assertFalse(tracker.snapshot()["complete"])

    def test_help_close_requires_continuous_hold_and_live_geometry(self):
        tracker, now = self.help_final_tracker()
        result = observation("help_close")
        tracker.observe(result, now)
        tracker.observe(result, now+299)
        self.assertEqual(tracker.index, 2)
        tracker.observe({"error_code": "NO_HAND"}, now+300)
        tracker.observe(result, now+400)
        tracker.observe(result, now+699)
        self.assertEqual(tracker.index, 2)
        tracker.observe(result, now+700)
        self.assertFalse(tracker.snapshot()["complete"])
        tracker, now = self.help_final_tracker()
        tracker.observe({"gesture_id": "FIST", "valid": True, "error_code": "OK"}, now)
        self.assertEqual(tracker.index, 0)

    def test_help_compact_thumb_can_be_mislabeled_by_real_static_rules(self):
        points = palm_shape((True,)*4)
        points[1:5] = [(0, .2), (0, .35), (0, .5), (0, .65)]
        result = dict(classify_gesture(points))
        result["motion_evidence"] = motion_evidence(points)
        self.assertEqual(result["gesture_id"], "THUMBS_UP")
        tracker, now = self.help_final_tracker()
        hold(tracker, result, now)
        self.assertFalse(tracker.snapshot()["complete"])

    def test_help_controller_records_review_separately_from_automatic_pass(self):
        controller, now = self.controller("signal_help"), 0
        for phase in ("palm_open", "thumb_in", "help_close"):
            result = observation(phase)
            if phase == "help_close":
                result.update(gesture_id="THUMBS_UP", confidence=.95, valid=True, error_code="OK")
            for delta in (0, 150, 320):
                controller.observe(result, now+delta)
            now += 400
        self.assertEqual(controller.state, "IMITATING")
        result = controller.review_manual(now, True, controller.session_token)
        self.assertEqual(result["state"], "REVIEWED")
        self.assertEqual(result["error_code"], "MANUAL_REVIEW")
        self.assertEqual(result["motion_progress"]["completed_steps"], 2)
        self.assertFalse(result["motion_progress"]["complete"])

    def test_five_automatic_sequences_complete_help_requires_review(self):
        for lesson, phases in SEQUENCES.items():
            with self.subTest(lesson=lesson):
                tracker, now = SignSequenceTracker(lesson), 0
                for index, (phase, _) in enumerate(phases):
                    now = hold(tracker, observation(phase), now)
                    self.assertEqual(tracker.index, min(index+1, 2) if lesson == "signal_help" else index+1)
                self.assertEqual(tracker.snapshot()["complete"], lesson != "signal_help")

    def test_final_shape_alone_never_completes_any_dynamic_lesson(self):
        for lesson, phases in SEQUENCES.items():
            with self.subTest(lesson=lesson):
                tracker = SignSequenceTracker(lesson)
                final = observation(phases[-1][0])
                for now in range(0, 3000, 150):
                    self.assertFalse(tracker.observe(final, now))
                self.assertFalse(tracker.snapshot()["complete"])

    def test_one_thumb_or_index_cycle_is_insufficient(self):
        for lesson in ("word_thanks", "word_attention"):
            tracker, now = SignSequenceTracker(lesson), 0
            for phase, _ in SEQUENCES[lesson][:3]:
                now = hold(tracker, observation(phase), now)
            self.assertEqual(tracker.index, 3)
            for tick in range(now, now+1800, 150):
                tracker.observe(observation(SEQUENCES[lesson][-1][0]), tick)
            self.assertEqual(tracker.index, 3)
            self.assertFalse(tracker.snapshot()["complete"])

    def test_bent_index_cannot_count_as_the_return_to_extension(self):
        tracker, now = SignSequenceTracker("word_attention"), 0
        for phase in ("index_open", "index_bend"):
            now = hold(tracker, observation(phase), now)
        for tick in range(now, now+1600, 150):
            tracker.observe(observation("index_bend"), tick)
        self.assertEqual(tracker.index, 2)

    def test_reversed_shape_sequence_and_skipped_help_phase_fail(self):
        for lesson in ("word_hello", "word_like", "signal_help"):
            tracker, now = SignSequenceTracker(lesson), 0
            now = hold(tracker, observation(SEQUENCES[lesson][-1][0]), now)
            self.assertEqual(tracker.index, 0)
            now = hold(tracker, observation(SEQUENCES[lesson][0][0]), now)
            self.assertEqual(tracker.index, 1)
            if lesson == "signal_help":
                hold(tracker, observation("shape:FIST"), now)
                self.assertEqual(tracker.index, 1)

    def test_invalid_geometry_and_sdk_errors_reset_all_progress(self):
        for bad in (dict(observation("thumb_open"), error_code="INVALID_LANDMARKS"),
                    {"error_code": "SDK_ERROR"}, {"error_code": "OK"}):
            tracker = SignSequenceTracker("word_thanks")
            hold(tracker, observation("thumb_open"), 0)
            tracker.observe(bad or {}, 400)
            self.assertEqual(tracker.index, 0)
            hold(tracker, observation("thumb_bend"), 500)
            self.assertEqual(tracker.index, 0)

    def test_long_gap_preserves_steps_but_does_not_earn_hold(self):
        for gap in (2001, 3000):
            tracker = SignSequenceTracker("word_thanks")
            hold(tracker, observation("thumb_open"), 0)
            tracker.observe(observation("thumb_bend"), 320+gap)
            self.assertEqual(tracker.index, 1)
            self.assertEqual(tracker.hold_ms, 0)
            tracker.observe(observation("thumb_bend"), 620+gap)
            self.assertEqual(tracker.index, 2)
        tracker = SignSequenceTracker("word_thanks")
        hold(tracker, observation("thumb_open"), 0)
        for now in range(400, 16000, 100):
            tracker.observe(observation("thumb_open"), now)
        self.assertEqual(tracker.index, 1)

    def test_jitter_and_duplicate_timestamp_never_advance(self):
        tracker = SignSequenceTracker("word_thanks")
        for _ in range(10):
            tracker.observe(observation("thumb_open"), 0)
        self.assertEqual(tracker.index, 0)
        for now in range(50, 1000, 50):
            tracker.observe(observation("thumb_open" if now % 100 else "thumb_bend"), now)
        self.assertEqual(tracker.index, 0)

    def test_nonfinite_and_boolean_evidence_is_rejected(self):
        for value in (float("nan"), float("inf"), True, "170", -1, 181):
            tracker = SignSequenceTracker("word_thanks")
            result = observation("thumb_open")
            result["motion_evidence"]["thumb_angle_deg"] = value
            hold(tracker, result, 0)
            self.assertEqual(tracker.index, 0)

    def test_lateral_same_side_or_small_amplitude_does_not_count(self):
        for value in (0.5, 0.2, 0.0):
            tracker = SignSequenceTracker("word_no")
            now = hold(tracker, observation("point_anchor"), 0)
            now = hold(tracker, observation("point_side"), now)
            same = observation("point_other")
            same["motion_evidence"]["index_lateral"] = value
            hold(tracker, same, now)
            self.assertEqual(tracker.index, 2)

    def test_mirrored_lateral_sequence_works(self):
        tracker, now = SignSequenceTracker("word_no"), 0
        for phase, _ in SEQUENCES["word_no"]:
            result = observation(phase)
            result["motion_evidence"]["index_lateral"] *= -1
            now = hold(tracker, result, now)
        self.assertTrue(tracker.snapshot()["complete"])

    def controller(self, lesson="word_thanks"):
        controller = SignLessonController()
        controller.select_lesson(lesson, 0)
        controller.start(0, manual_confirm=True, link_online=True, vision_fresh=True)
        controller.begin_demo(0, link_online=True, vision_fresh=True)
        controller.finish_demo(0, link_online=True, vision_fresh=True)
        return controller

    def test_controller_final_static_result_does_not_complete(self):
        controller = self.controller()
        result = {"gesture_id": "THUMBS_UP", "confidence": .99, "stable_ms": 10000,
                  "valid": True, "error_code": "OK"}
        for now in (0, 300, 600):
            self.assertEqual(controller.observe(result, now)["state"], "IMITATING")
        self.assertEqual(controller.status()["motion_progress"]["completed_steps"], 0)

    def test_controller_completes_only_after_all_phases_and_resets_session(self):
        controller, now = self.controller(), 0
        for phase, _ in SEQUENCES["word_thanks"]:
            for delta in (0, 150, 320):
                controller.observe(observation(phase), now+delta)
            now += 400
        self.assertEqual(controller.state, "COMPLETE")
        self.assertTrue(controller.status()["motion_progress"]["complete"])
        controller.select_lesson("word_thanks", now)
        self.assertEqual(controller.status()["motion_progress"]["completed_steps"], 0)
        controller.reset(now)
        self.assertNotIn("motion_progress", controller.status())

    def test_controller_null_observation_link_fault_and_timeout_fail_closed(self):
        controller = self.controller()
        for now in (0, 320):
            controller.observe(observation("thumb_open"), now)
        controller.observe(None, 400)
        self.assertEqual(controller.status()["motion_progress"]["completed_steps"], 1)
        self.assertEqual(controller.observe(observation("thumb_open"), 500, link_online=False)["state"], "FAULT")
        controller = self.controller()
        self.assertEqual(controller.tick(controller.dynamic_timeout_ms)["state"], "TIMEOUT")

    def test_brief_loss_preserves_steps_but_restarts_current_hold(self):
        for bad in (None, {}, {"error_code": "NO_HAND"}, {"error_code": "hand_not_found"}):
            tracker = SignSequenceTracker("word_thanks")
            hold(tracker, observation("thumb_open"), 0)
            tracker.observe(observation("thumb_bend"), 400)
            tracker.observe(bad, 600)
            self.assertEqual(tracker.index, 1)
            self.assertEqual(tracker.hold_ms, 0)
            tracker.observe(observation("thumb_bend"), 800)
            self.assertEqual(tracker.index, 1)  # missing time earns nothing
            tracker.observe(observation("thumb_bend"), 1100)
            self.assertEqual(tracker.index, 2)

    def test_repeated_missing_frames_preserve_steps_but_cannot_complete(self):
        for error in ("NO_HAND", "hand_not_found"):
            tracker = SignSequenceTracker("word_thanks")
            hold(tracker, observation("thumb_open"), 0)
            for now in range(400, 20000, 100):
                self.assertFalse(tracker.observe({"error_code": error}, now))
            self.assertEqual(tracker.index, 1)
            self.assertEqual(tracker.count, 0)
            self.assertEqual(tracker.hold_ms, 0)
            self.assertFalse(tracker.snapshot()["complete"])

    def test_help_transition_preserves_confirmed_steps_but_earns_no_hold(self):
        tracker, now = self.help_final_tracker()
        tracker.observe(observation("help_close"), now)
        tracker.observe({"error_code": "hand_not_found", "valid": False,
                         "gesture_id": None, "stable_ms": 0}, now+150)
        self.assertEqual(tracker.index, 2)
        self.assertEqual(tracker.hold_ms, 0)
        self.assertEqual(tracker.snapshot()["checks"], [])
        self.assertEqual(tracker.snapshot()["observation_state"], "MISSING")
        transition = observation("thumb_in")
        self.assertEqual(transition["gesture_id"], "UNKNOWN")
        tracker.observe(transition, now+300)
        self.assertEqual(tracker.index, 2)
        self.assertEqual(tracker.hold_ms, 0)
        tracker.observe(observation("help_close"), now+450)
        tracker.observe(observation("help_close"), now+749)
        self.assertFalse(tracker.snapshot()["complete"])
        tracker.observe(observation("help_close"), now+750)
        self.assertFalse(tracker.snapshot()["complete"])

    def test_all_sequences_can_resume_after_short_interstage_loss(self):
        for lesson, phases in SEQUENCES.items():
            tracker, now = SignSequenceTracker(lesson), 0
            for index, (phase, _) in enumerate(phases):
                if index:
                    tracker.observe({"error_code": "NO_HAND"}, now)
                    self.assertEqual(tracker.index, index)
                    now += 400
                now = hold(tracker, observation(phase), now)
                self.assertEqual(tracker.index, min(index+1, 2) if lesson == "signal_help" else index+1)
            self.assertEqual(tracker.snapshot()["complete"], lesson != "signal_help")

    def test_waiting_for_next_phase_does_not_erase_confirmed_steps(self):
        tracker = SignSequenceTracker("word_thanks")
        hold(tracker, observation("thumb_open"), 0)
        for now in range(400, 15501, 200):
            tracker.observe(observation("thumb_open"), now)
        self.assertEqual(tracker.index, 1)
        self.assertEqual(tracker.hold_ms, 0)
        hold(tracker, observation("thumb_bend"), 16000)
        self.assertEqual(tracker.index, 2)

    def test_help_controller_preserves_steps_for_review_after_pause(self):
        controller = self.controller("signal_help")
        for phase, start in (("palm_open", 0), ("thumb_in", 400)):
            for delta in (0, 150, 320):
                controller.observe(observation(phase), start+delta)
        controller.observe(observation("help_close"), 800)
        for now in (1000, 5000, 15000, 25000):
            controller.observe({"error_code": "hand_not_found"}, now)
            self.assertEqual(controller.state, "IMITATING")
            self.assertEqual(controller.status()["motion_progress"]["completed_steps"], 2)
            self.assertEqual(controller.status()["motion_progress"]["phase_hold_ms"], 0)
        controller.observe(observation("help_close"), 30000)
        controller.observe(observation("help_close"), 30299)
        self.assertEqual(controller.state, "IMITATING")
        controller.observe(observation("help_close"), 30300)
        self.assertEqual(controller.state, "IMITATING")
        self.assertEqual(controller.review_manual(30301, True, controller.session_token)["state"], "REVIEWED")

    def test_paused_help_cannot_bypass_overall_deadline(self):
        controller = self.controller("signal_help")
        for phase, start in (("palm_open", 0), ("thumb_in", 400)):
            for delta in (0, 320):
                controller.observe(observation(phase), start+delta)
        for now in (1000, 5000, 25000, 59999):
            controller.observe({"error_code": "hand_not_found"}, now)
        status = controller.observe(observation("help_close"), 60000)
        self.assertEqual(status["state"], "TIMEOUT")
        self.assertFalse(status["motion_progress"]["complete"])

    def test_sparse_samples_do_not_earn_continuous_hold(self):
        tracker = SignSequenceTracker("word_thanks")
        for now in (0, 600, 1200, 1800):
            tracker.observe(observation("thumb_open"), now)
        self.assertEqual(tracker.index, 0)
        self.assertEqual(tracker.hold_ms, 0)

    def test_slow_switch_over_four_seconds_preserves_ordered_progress(self):
        tracker = SignSequenceTracker("word_thanks")
        hold(tracker, observation("thumb_open"), 0)
        for now in range(400, 5400, 200):
            tracker.observe(observation("thumb_open"), now)
        self.assertEqual(tracker.index, 1)
        hold(tracker, observation("thumb_bend"), 5400)
        self.assertEqual(tracker.index, 2)

    def test_clock_reversal_resets_without_earning_a_step(self):
        tracker = SignSequenceTracker("word_thanks")
        hold(tracker, observation("thumb_open"), 0)
        tracker.observe(observation("thumb_bend"), 100)
        self.assertEqual(tracker.index, 0)

    def test_dynamic_budget_is_longer_without_changing_static_timeout(self):
        controller = self.controller()
        self.assertEqual(controller.tick(15000)["state"], "IMITATING")
        self.assertEqual(controller.tick(59999)["state"], "IMITATING")
        self.assertEqual(controller.tick(60000)["state"], "TIMEOUT")
        controller = self.controller("basic_thumbs_up")
        self.assertEqual(controller.tick(15000)["state"], "TIMEOUT")

    def test_static_course_remains_unchanged(self):
        controller = self.controller("basic_thumbs_up")
        result = {"gesture_id": "THUMBS_UP", "confidence": .95, "stable_ms": 300,
                  "valid": True, "error_code": "OK"}
        self.assertEqual(controller.observe(result, 300)["state"], "COMPLETE")
        self.assertNotIn("motion_progress", controller.status())

    def test_synthetic_thumb_landmarks_drive_both_cycles_through_real_geometry(self):
        extended = palm_shape((True,)*4)
        extended[1:5] = [(0, .5), (0, 1), (0, 2), (0, 3)]
        bent = list(extended)
        bent[2:5] = [(0.1, .7), (.3, .7), (.3, .4)]
        tracker, now = SignSequenceTracker("word_thanks"), 0
        for points in (extended, bent, extended, bent, extended):
            result = dict(classify_gesture(points))
            result["motion_evidence"] = motion_evidence(points)
            now = hold(tracker, result, now)
        self.assertTrue(tracker.snapshot()["complete"])

    def test_shape_stage_rejects_boolean_confidence_and_low_score(self):
        for confidence in (True, float("nan"), .3):
            tracker = SignSequenceTracker("word_hello")
            result = observation("shape:POINT")
            result["confidence"] = confidence
            hold(tracker, result, 0)
            self.assertEqual(tracker.index, 0)

    def test_geometry_is_rotation_scale_translation_invariant(self):
        points = palm_shape((False, True, True, True))
        points[1:5] = [(0.3, 0.1), (0.8, 0.2), (1.3, 0.3), (1.8, 0.4)]
        a = motion_evidence(points)
        b = motion_evidence([(200-y*5, 150+x*5) for x, y in points])
        for key in ("thumb_angle_deg", "index_angle_deg", "index_lateral", "thumb_tip_distance"):
            self.assertAlmostEqual(a[key], b[key], places=5)
        for first, second in zip(a["finger_extension"], b["finger_extension"]):
            self.assertAlmostEqual(first, second, places=6)
        self.assertEqual(a["thumb_inside"], b["thumb_inside"])
        self.assertEqual(classify_gesture(points).gesture_id, "L_SHAPE")


if __name__ == "__main__":
    unittest.main()
