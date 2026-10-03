"""Run the voice_app state-machine assertions and wrap them for Python.

Same contract as the rest of the suite: the assertions live in
tests/test_voice_app_c.c, and this module makes them run under
`python -m unittest smart_hand.tests.*` and turns a silently-missing case into a
failure rather than a green suite.

It also carries the mutation tests, because "the guard is covered" is a claim
that has to be falsified rather than asserted. Each mutation deletes one of the
three rules voice_app.h states, rebuilds against a patched copy of voice_app.c,
and requires a *named* case to fail. A mutation that fails to apply, fails to
compile, or is caught by nothing is reported as a failure of the mutation suite
itself -- otherwise a needle that no longer matches the source would make the
whole exercise vacuously green.

The mutations are deliberately applied to a copy in a temp directory. The
repository copy of voice_app.c is never written to.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TITAN_DIR = PROJECT_ROOT / "titan_rtthread"
TESTS_DIR = PROJECT_ROOT / "tests"

TEST_C = TESTS_DIR / "test_voice_app_c.c"
APP_C = TITAN_DIR / "voice_app.c"
APP_H = TITAN_DIR / "voice_app.h"
TEST_EXE = TESTS_DIR / "test_voice_app_c.exe"

CFLAGS = ["-std=gnu11", "-Wall", "-Wextra"]

# Every case main() runs, in order. A case that stops reporting is a coverage
# regression, not a formatting change.
EXPECTED_CASES = [
    "1-cold-start-window-then-result",
    "2-short-window-is-not-inferred",
    "3-overrun-discards-and-recovers",
    "4-inference-failure-publishes-no-stale-result",
    "5-unusable-decision-is-model-error",
    "6-capture-start-failure-is-audio-error",
    "7-stop-then-restart-recovers",
    "8-disabled-reports-disabled",
    "9-overrun-during-copy-is-caught",
    "10-sustained-overrun-never-infers",
    "11-window-buffer-is-the-callers",
    "12-evidence-flags-and-health-mirror",
]

# The pristine run reports 277 checks. The floor exists to catch a case that
# keeps its name but loses its assertions; it is not a target to keep in step.
MIN_CHECKS = 200

# The ok and FAILED case lines do NOT have the same shape: a passing case
# prints "(N checks)" and a failing one prints "(M failures, N checks)". A
# single pattern written against the passing shape silently matches no failing
# case at all, which makes "no case reported FAILED" true by construction --
# and would have made every mutation below look uncaught.
OK_CASE_LINE = re.compile(r"^\[case\] (\S+): ok \((\d+) checks\)$")
FAILED_CASE_LINE = re.compile(
    r"^\[case\] (\S+): FAILED \((\d+) failures, (\d+) checks\)$"
)
PASSED_LINE = re.compile(
    r"^C voice app tests passed \((\d+) checks\)$", re.MULTILINE
)


class Mutation:
    """One surgical edit that removes exactly one of the state machine's rules.

    `needle` must appear exactly once in voice_app.c; the count is checked
    before anything is built, so a needle that has drifted out of the source is
    a loud failure instead of a no-op.
    """

    def __init__(self, slug, rule, needle, replacement, caught_by, why):
        self.slug = slug
        self.rule = rule
        self.needle = needle
        self.replacement = replacement
        self.caught_by = caught_by
        self.why = why

    def __repr__(self):
        return f"<Mutation {self.slug}>"


MUTATIONS = [
    Mutation(
        slug="M1-window-completeness-guard-removed",
        rule="R1",
        needle="    if (available < (uint32_t)VOICE_WINDOW_SAMPLES)\n",
        replacement="    if (0)\n",
        caught_by="2-short-window-is-not-inferred",
        why=(
            "R1: the check on take_window()'s return value is the only thing "
            "stopping a partially filled ring from being classified as if it "
            "were a whole window."
        ),
    ),
    Mutation(
        slug="M2-overrun-discard-removed",
        rule="R2",
        needle=(
            "    if ((overrun_after != overrun_before) ||\n"
            "        (overrun_after != app->last_overrun))\n"
        ),
        replacement="    if (0)\n",
        caught_by="3-overrun-discards-and-recovers",
        why=(
            "R2: without this, a window spliced across a ring overrun is "
            "inferred instead of abandoned."
        ),
    ),
    Mutation(
        slug="M3-stale-result-republished-on-failure",
        rule="R3",
        needle=(
            "    voice_app_invalidate_result(app);\n"
            "    app->cycles_failed += 1U;\n"
        ),
        replacement="    app->cycles_failed += 1U;\n",
        caught_by="4-inference-failure-publishes-no-stale-result",
        why=(
            "R3: dropping the invalidation leaves result_valid set after an "
            "inference failure, so the previous class keeps looking current."
        ),
    ),
    Mutation(
        slug="M4-decision-validation-removed",
        rule="R3",
        needle=(
            "    if ((decision.class_index < 0) ||\n"
            "        !((decision.confidence >= 0.0f) && "
            "(decision.confidence <= 1.0f)))\n"
        ),
        replacement="    if (0)\n",
        caught_by="5-unusable-decision-is-model-error",
        why=(
            "R3: without the usability test, a negative class index or a NaN "
            "confidence is published as if it were a decision. A NaN is the "
            "interesting one -- it survives naive `<` comparisons."
        ),
    ),
]


# errors="replace" on both capture calls is load-bearing, not decoration.
#
# gcc and the test binaries echo ABSOLUTE paths, and this project lives under a
# directory whose name is not ASCII. Those bytes come back in the console's own
# encoding while Python decodes as UTF-8, and without errors="replace" the
# reader thread raises UnicodeDecodeError, subprocess hands back stdout=None, and
# parse_cases() dies on None.
#
# The failure mode was the reverse of a silent one: it fired exactly when a
# mutation WAS caught, because that is when the C output prints "FAIL <path>".
# So the mutation suites reported an error instead of a caught mutation, and the
# coverage claim they exist to falsify could not be checked at all.
def build(sources, exe, include_dirs, extra=()):
    cmd = ["gcc", *CFLAGS, *extra]
    for directory in include_dirs:
        cmd += ["-I", str(directory)]
    cmd += [str(src) for src in sources]
    cmd += ["-o", str(exe), "-lm"]
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace")


def run(exe):
    return subprocess.run([str(exe)], capture_output=True, text=True,
                          errors="replace")


def parse_cases(stdout):
    cases = {}
    for line in stdout.splitlines():
        match = OK_CASE_LINE.match(line)
        if match:
            cases[match.group(1)] = ("ok", int(match.group(2)))
            continue
        match = FAILED_CASE_LINE.match(line)
        if match:
            cases[match.group(1)] = ("FAILED", int(match.group(3)))
    return cases


class VoiceAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sources = [TEST_C, APP_C, APP_H]
        if not TEST_EXE.exists() or any(
            TEST_EXE.stat().st_mtime < src.stat().st_mtime for src in sources
        ):
            built = build([TEST_C, APP_C], TEST_EXE, [TITAN_DIR])
            if built.returncode != 0:
                raise AssertionError(
                    "failed to build the voice app test:\n" + built.stderr
                )
        cls.result = run(TEST_EXE)
        cls.cases = parse_cases(cls.result.stdout)
        cls.app_source = APP_C.read_text(encoding="utf-8")

    def _failure_note(self, message):
        return "%s\n--- stdout ---\n%s\n--- stderr ---\n%s" % (
            message, self.result.stdout, self.result.stderr,
        )

    def test_c_assertions_pass(self):
        self.assertEqual(
            self.result.returncode, 0,
            self._failure_note("voice app assertions failed"),
        )
        self.assertNotIn("FAIL ", self.result.stdout)
        self.assertIsNotNone(
            PASSED_LINE.search(self.result.stdout),
            self._failure_note("the pass marker is missing"),
        )

    def test_every_case_reports_ok(self):
        missing = [name for name in EXPECTED_CASES if name not in self.cases]
        failed = [name for name, (status, _) in self.cases.items()
                  if status != "ok"]
        self.assertEqual(missing, [], self._failure_note("cases did not run"))
        self.assertEqual(
            failed, [], self._failure_note("cases reported FAILED"),
        )

    def test_check_count_did_not_collapse(self):
        marker = PASSED_LINE.search(self.result.stdout)
        if marker is None:
            self.fail(self._failure_note("no check count to read"))
        total = int(marker.group(1))
        self.assertGreaterEqual(
            total, MIN_CHECKS,
            self._failure_note(
                "only %d checks ran; a case may have lost its assertions" % total
            ),
        )

    def test_evidence_flags_are_never_set_by_the_module(self):
        """The module must not be able to claim validation it has not got.

        A grep is the right tool here rather than a runtime assertion: the
        flags are struct fields, so a future code path could assign to them and
        every case above would still pass as long as it assigned 0 or was never
        reached.

        Only stores into the module's own state count. voice_app_status()
        legitimately *reads* the flags out into the caller's status block, and
        voice_app_init()'s memset zeroes them; neither is a claim of evidence.
        """
        body = re.sub(r"/\*.*?\*/", "", self.app_source, flags=re.DOTALL)
        for field in ("field_accuracy_validated", "hardware_inference_validated"):
            stores = [
                line.strip()
                for line in body.splitlines()
                if re.search(
                    r"\bapp\s*(?:->|\.)\s*%s\s*(=[^=]|\+\+|--|\+=)" % field,
                    line,
                )
            ]
            self.assertEqual(
                stores, [],
                "voice_app.c stores into app->%s; only a reviewed human edit "
                "that follows real evidence may do that: %r" % (field, stores),
            )


GLUE_C = TESTS_DIR / "test_voice_app_titan_c.c"
GLUE_H = TITAN_DIR / "voice_app_titan.h"
GLUE_C_SOURCE = TITAN_DIR / "voice_app_titan.c"
GLUE_EXE = TESTS_DIR / "test_voice_app_titan_c.exe"
GLUE_EXE_DISABLED = TESTS_DIR / "test_voice_app_titan_c_disabled.exe"
VOICEAPP_STUBS = TESTS_DIR / "stubs_voiceapp"
GENERATED_DIR = PROJECT_ROOT / "titan_ai" / "voice" / "generated"

GLUE_SOURCES = [
    GLUE_C,
    TITAN_DIR / "voice_app_titan.c",
    TITAN_DIR / "voice_app.c",
    TITAN_DIR / "voice_features.c",
    TITAN_DIR / "voice_kws.c",
    TITAN_DIR / "voice_audio.c",
    GENERATED_DIR / "voice_model_data.c",
]

GLUE_INCLUDES = [VOICEAPP_STUBS, TITAN_DIR, GENERATED_DIR]

GLUE_CASES_ENABLED = [
    "1-thread-parameters-match-the-requirement",
    "2-thread-opens-capture-and-polls",
    "3-real-window-publishes-a-result",
    "4-ring-overrun-blocks-publication",
    "5-snapshot-leaves-the-interrupt-mask-balanced",
    "6-capture-start-failure-is-survivable",
    "7-sustained-windows-keep-the-ring-draining",
    "8-window-spans-a-ring-wrap-in-order",
    "9-producer-cannot-overwrite-an-unread-window",
    "10-inference-longer-than-a-window-recovers",
]

GLUE_CASES_DISABLED = ["0-compiled-out-is-inert"]

# Headers and calls that would put the voice module on the motion path. This
# stage is passive by contract, so the check is on the source rather than on a
# behaviour the test would have to provoke.
FORBIDDEN_IN_GLUE = [
    "servo_bus_readonly_rt.h",
    "servo_safety_gate.h",
    "eight_servo_safety_gate.h",
    "eight_servo_pose_bank.h",
    "smart_hand_uart.h",
    "grip_policy.h",
    "scs0009_",
    "eight_servo_",
    "rt_device_write",
    "servo_",
]


class VoiceAppTitanGlueTests(unittest.TestCase):
    """The RT-Thread glue, built both ways.

    The policy tests above run against a scripted I/O table, which cannot see
    the thread's priority, its stack size, or whether the compile-time switch
    really removes everything -- those are properties of the build. This class
    builds the same source twice, once per switch setting.
    """

    @classmethod
    def setUpClass(cls):
        cls.runs = {}
        for enabled, exe in ((1, GLUE_EXE), (0, GLUE_EXE_DISABLED)):
            cls.runs[enabled] = cls._build_and_run(enabled, exe)

    @classmethod
    def _build_and_run(cls, enabled, exe):
        newest = max(src.stat().st_mtime for src in GLUE_SOURCES + [GLUE_H])
        if not exe.exists() or exe.stat().st_mtime < newest:
            built = build(
                GLUE_SOURCES, exe, GLUE_INCLUDES,
                extra=[f"-DVOICE_APP_ENABLE={enabled}"],
            )
            if built.returncode != 0:
                return {"build_error": built.stderr}
        result = run(exe)
        return {
            "result": result,
            "cases": parse_cases(result.stdout),
        }

    def _glue_run(self, enabled):
        # Not named _outcome(): TestCase already owns that attribute.
        outcome = self.runs[enabled]
        self.assertNotIn(
            "build_error", outcome,
            "glue build failed with VOICE_APP_ENABLE=%d:\n%s"
            % (enabled, outcome.get("build_error", "")),
        )
        return outcome

    def _assert_clean(self, enabled, expected_cases):
        outcome = self._glue_run(enabled)
        result = outcome["result"]
        note = "VOICE_APP_ENABLE=%d\n%s\n%s" % (
            enabled, result.stdout, result.stderr,
        )
        self.assertEqual(result.returncode, 0, "glue assertions failed\n" + note)
        self.assertNotIn("FAIL ", result.stdout, note)
        missing = [name for name in expected_cases if name not in outcome["cases"]]
        failed = [name for name, (status, _) in outcome["cases"].items()
                  if status != "ok"]
        self.assertEqual(missing, [], "cases did not run\n" + note)
        self.assertEqual(failed, [], "cases reported FAILED\n" + note)

    def test_glue_cases_pass_when_enabled(self):
        self._assert_clean(1, GLUE_CASES_ENABLED)

    def test_compiled_out_build_is_inert(self):
        self._assert_clean(0, GLUE_CASES_DISABLED)

    def test_thread_priority_is_below_sh_uart(self):
        """The one number the module cannot express in its own state.

        RT-Thread runs the smallest priority number first, so the voice thread
        must be strictly greater than sh_uart's 18. The C case asserts it
        against what was handed to rt_thread_init(); this one reads the macros,
        so a change to either constant is caught even if the two are changed
        together into an illegal pair.
        """
        text = GLUE_H.read_text(encoding="utf-8")

        def macro(name):
            match = re.search(
                r"^#define\s+%s\s+\((\d+)U?\)" % name, text, re.MULTILINE
            )
            self.assertIsNotNone(match, f"{name} is not defined in {GLUE_H.name}")
            return int(match.group(1))

        voice = macro("VOICE_APP_THREAD_PRIORITY")
        uart = macro("VOICE_APP_SH_UART_PRIORITY")
        stack = macro("VOICE_APP_THREAD_STACK")

        self.assertEqual(uart, 18, "the sh_uart priority this file mirrors moved")
        self.assertGreater(
            voice, uart,
            "the voice thread (%d) is not lower priority than sh_uart (%d)"
            % (voice, uart),
        )
        self.assertGreaterEqual(
            stack, 6144,
            "the voice stack (%d B) is under the 6 KB floor" % stack,
        )
        self.assertEqual(stack, 8192)

    def test_glue_stays_off_the_motion_path(self):
        """Passive integration is a constraint on the source, not a promise."""
        source = GLUE_C_SOURCE.read_text(encoding="utf-8")
        # Strip comments: the file talks about servos at length in prose.
        body = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
        body = re.sub(r"//[^\n]*", "", body)

        found = sorted({token for token in FORBIDDEN_IN_GLUE if token in body})
        self.assertEqual(
            found, [],
            "voice_app_titan.c reaches into the motion/command path: %r" % found,
        )


class VoiceAppMutationTests(unittest.TestCase):
    """Each rule is deleted in turn and a named case must notice.

    These are the tests that make the coverage claim in test_voice_app_c.c
    falsifiable. They build from a patched copy of voice_app.c in a temp
    directory, so the repository source is untouched.
    """

    @classmethod
    def setUpClass(cls):
        cls.original = APP_C.read_text(encoding="utf-8")
        cls.results = {}
        for mutation in MUTATIONS:
            cls.results[mutation.slug] = cls._evaluate(mutation)

    @classmethod
    def _evaluate(cls, mutation):
        occurrences = cls.original.count(mutation.needle)
        if occurrences != 1:
            return {
                "ok": False,
                "note": (
                    "needle appears %d times in voice_app.c, expected exactly "
                    "1; the mutation would not have removed anything"
                    % occurrences
                ),
            }

        mutated = cls.original.replace(mutation.needle, mutation.replacement)
        if mutated == cls.original:
            return {"ok": False, "note": "the mutation did not change the source"}

        workdir = Path(tempfile.mkdtemp(prefix="voice_app_mutation_"))
        try:
            patched = workdir / "voice_app.c"
            patched.write_text(mutated, encoding="utf-8")
            exe = workdir / "mutant.exe"

            built = build([TEST_C, patched], exe, [TITAN_DIR])
            if built.returncode != 0:
                # A mutant that will not compile proves nothing about the
                # tests, so it is a failure of this suite rather than a pass.
                return {
                    "ok": False,
                    "note": "the mutant failed to build:\n" + built.stderr,
                }

            result = run(exe)
            cases = parse_cases(result.stdout)
            caught = [
                name for name, (status, _) in cases.items() if status == "FAILED"
            ]
            return {
                "ok": result.returncode != 0 and mutation.caught_by in caught,
                "note": (
                    "exit=%d, cases that failed: %s, expected %r to be among "
                    "them" % (result.returncode, caught or "none",
                              mutation.caught_by)
                ),
                "caught": caught,
                "stdout": result.stdout,
            }
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _assert_caught(self, slug):
        outcome = self.results[slug]
        self.assertTrue(outcome["ok"], outcome["note"])

    def test_m1_window_completeness_guard_is_load_bearing(self):
        self._assert_caught("M1-window-completeness-guard-removed")

    def test_m2_overrun_discard_is_load_bearing(self):
        self._assert_caught("M2-overrun-discard-removed")

    def test_m3_stale_result_invalidation_is_load_bearing(self):
        self._assert_caught("M3-stale-result-republished-on-failure")

    def test_m4_decision_validation_is_load_bearing(self):
        self._assert_caught("M4-decision-validation-removed")

    def test_every_rule_has_a_mutation(self):
        """A rule with no mutation is a rule whose coverage is unproven."""
        self.assertEqual(
            sorted({m.rule for m in MUTATIONS}), ["R1", "R2", "R3"],
        )
        # And no two mutations may target the same source text, or one edit
        # would be silently shadowing the other.
        needles = [m.needle for m in MUTATIONS]
        self.assertEqual(len(needles), len(set(needles)))


# -------------------------------------------------------------------------
# Glue mutations.
#
# The rules in voice_app.c are falsified above. The defect this batch fixed
# lived one layer out, in the RT-Thread glue: voice_io_take_window() had been
# mapped to a NON-CONSUMING read of the ring, so no code path ever advanced
# read_index. The 32,768-sample ring accepted 32,000 samples and then refused
# every later block, accepted_samples stopped advancing, and the R2 quarantine
# -- which waits for a whole window of newly ACCEPTED samples -- could never be
# satisfied. Capture parked in CAPTURING for good.
#
# Case 7 is the regression test for that. Restoring the old call is the only
# mechanical proof that case 7 detects the defect rather than merely passing
# alongside it, which is why this mutation is here and not left to prose.

GLUE_MUTATIONS = [
    Mutation(
        slug="G1-window-request-goes-back-to-a-non-consuming-read",
        rule="capture-consumes-its-window",
        needle="    return voice_ring_take_window(ring, out, count);\n",
        replacement="    return voice_ring_peek_latest(ring, out, count);\n",
        caught_by="7-sustained-windows-keep-the-ring-draining",
        why=(
            "The pre-fix glue, restored verbatim. peek_latest does not move "
            "read_index, so the ring fills and stays full: push() fails closed "
            "on every later block, total_samples freezes at 32,000, and the "
            "overrun counter climbs while the quarantine waits for accepted "
            "samples that can never arrive."
        ),
    ),
]


class VoiceAppTitanGlueMutationTests(unittest.TestCase):
    """Falsifies the glue's consuming window request.

    Built the same way as the real glue suite -- same sources, same includes,
    same VOICE_APP_ENABLE=1 -- with the patched voice_app_titan.c substituted
    for the repository copy. The repository file is never written to.
    """

    @classmethod
    def setUpClass(cls):
        cls.original = GLUE_C_SOURCE.read_text(encoding="utf-8")
        cls.results = {}
        for mutation in GLUE_MUTATIONS:
            cls.results[mutation.slug] = cls._evaluate(mutation)

    @classmethod
    def _evaluate(cls, mutation):
        occurrences = cls.original.count(mutation.needle)
        if occurrences != 1:
            return {
                "ok": False,
                "note": (
                    "needle appears %d times in voice_app_titan.c, expected "
                    "exactly 1; the mutation would not have removed anything"
                    % occurrences
                ),
            }

        mutated = cls.original.replace(mutation.needle, mutation.replacement)
        if mutated == cls.original:
            return {"ok": False, "note": "the mutation did not change the source"}

        workdir = Path(tempfile.mkdtemp(prefix="voice_glue_mutation_"))
        try:
            patched = workdir / "voice_app_titan.c"
            patched.write_text(mutated, encoding="utf-8")

            # Substitute, do not append: the temp copy must REPLACE the
            # repository one, or the mutant would be linked alongside the real
            # glue and the duplicate symbols would fail the build.
            sources = [
                patched if src == GLUE_C_SOURCE else src for src in GLUE_SOURCES
            ]
            exe = workdir / "mutant.exe"

            built = build(
                sources, exe, GLUE_INCLUDES, extra=["-DVOICE_APP_ENABLE=1"],
            )
            if built.returncode != 0:
                # A mutant that will not compile proves nothing about the tests.
                return {
                    "ok": False,
                    "note": "the mutant failed to build:\n" + built.stderr,
                }

            result = run(exe)
            cases = parse_cases(result.stdout)
            caught = [
                name for name, (status, _) in cases.items() if status == "FAILED"
            ]
            return {
                "ok": result.returncode != 0 and mutation.caught_by in caught,
                "note": (
                    "exit=%d, cases that failed: %s, expected %r to be among "
                    "them" % (result.returncode, caught or "none",
                              mutation.caught_by)
                ),
            }
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def test_g1_consuming_window_request_is_load_bearing(self):
        outcome = self.results[
            "G1-window-request-goes-back-to-a-non-consuming-read"
        ]
        self.assertTrue(outcome["ok"], outcome["note"])

    def test_each_glue_mutation_names_a_case_that_exists(self):
        """A caught_by that names no case would make the check vacuous.

        The case names live in the C file's run_case() calls rather than in a
        Python list, so they are read from the source. GLUE_CASES_ENABLED is
        checked against them by test_glue_cases_pass_when_enabled() at run time.
        """
        declared = set(
            re.findall(r'run_case\("([^"]+)"', GLUE_C.read_text(encoding="utf-8"))
        )
        self.assertNotEqual(declared, set(), "no run_case() calls found")
        for mutation in GLUE_MUTATIONS:
            self.assertIn(
                mutation.caught_by, declared,
                "mutation %s expects case %r, which no run_case() declares"
                % (mutation.slug, mutation.caught_by),
            )


if __name__ == "__main__":
    unittest.main()
