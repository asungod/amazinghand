# Rehabilitation session integration — 2026-08-22

## Implemented workflow

1. YOLO target selection remains advisory.
2. The physical-screen release edge sends the explicit `TRAIN` request.
3. Titan remains the sole mechanical-motion authority.
4. Only a matching authoritative `TRAINSTAT ... SUCCEEDED` event starts the user-imitation phase.
5. MaixCAM2 releases YOLO/camera resources, loads `HandLandmarks`, and disables further training requests.
6. The user performs five stable open-close-open repetitions within 60 seconds.
7. During user imitation, no `VISION` action payload is sent and the display states `ROBOT MOTION LOCKED`.
8. After completion/timeout is held for three seconds, the hand model is released and YOLO target mode is restored.

## Fail-closed behavior

- Detection alone cannot start either robot motion or the user session.
- Missing/mid hand frames do not count.
- Late frames after timeout do not count.
- Hand-model initialization failure enters a timed terminal state and restores target mode.
- Titan PING/STATUS processing continues during the vision phase transition.
- Absence of action `VISION` frames during imitation makes Titan's vision authority stale rather than actionable.

## Validation status

- Pure state-machine and main-loop helper tests: passed offline.
- Full repository check suite: passed before deployment.
- Standalone hand-landmark recognition and six user repetitions: passed on MaixCAM2.
- In-process YOLO → HandLandmarks → YOLO resource transition: **passed on MaixCAM2**.
- Integrated software sequence (target → Titan-authoritative demonstration completion → five user repetitions → target-mode restoration): **passed**.
- Physical observation of the robot demonstration in this exact integrated run: **passed; operator confirmed normal motion with no abnormal sound**.

## Integrated run evidence

- Source log SHA-256: `BB564ADFA03A709FD61EB90F78A60A39EDB9C7831522DA1732D0474D8E4F51A8`.
- Titan events were ordered `TRAIN QUEUED` → `TRAIN RUNNING` → `TRAIN COMPLETE REP=1 17.9s`.
- MaixCAM2 then reported `USER IMITATION START goal=5` and `VISION PHASE HAND: YOLO released; motion request disabled`.
- The terminal reported `USER REPETITION 1 COMPLETE` through `USER REPETITION 5 COMPLETE`.
- MaixCAM2 released the hand model and reported `VISION PHASE TARGET: hand model released; YOLO restored`.
- Link totals reached `sent=160`, `acked=160`, with zero TX failures, rejects, unexpected frames, malformed frames, timeouts, and pending frames.
- No traceback or nonzero vision read-error counter appeared in the captured log.

The operator subsequently confirmed that the robot demonstration in this exact
integrated run completed the full close-hold-open motion with no abnormal sound
or observed fault. The integrated hardware workflow is therefore **passed**.

## Result-page follow-up

The user-imitation terminal state now remains visible for eight seconds and
shows outcome, repetitions/goal, completion percentage, total duration, and
average duration per completed repetition. Timeout produces an explicit
`INCOMPLETE` result; it is never promoted to a pass. A structured
`USER SESSION RESULT` line provides the same metrics for later report export.
Robot motion remains locked throughout this result display.

## Session history follow-up

Each terminal user session is now appended once to
`/root/smart_hand_rehab_sessions.csv`. The record contains a schema version,
monotonic session number, outcome, repetition count and goal, completion
percentage, Titan demonstration duration, imitation duration, and average
duration per completed repetition. It contains no patient identity or clinical
diagnosis. A storage failure is reported to the console but cannot change the
motion-authority or fail-closed state machines.

The host utility `host/generate_rehab_session_report.py` converts the exported
CSV into a standalone HTML summary with session count, completed sessions,
total repetitions, average completion percentage, and per-session timing. It
validates the CSV schema and internal completion percentage before rendering
and includes an explicit non-clinical-use boundary.

The 60-second no-imitation hardware timeout produced `INCOMPLETE 0/5`, saved a
single TIMEOUT session, restored YOLO target mode, and kept the UART link free
of errors. This confirms the software failure path does not convert missing
user motion into a successful training result.

## Configurable repetition goal

The target screen now provides a separate release-edge `GOAL` button cycling
through 5, 10, and 15 repetitions. The selected goal changes only while the
system is in idle target mode; it locks as soon as a TRAIN request is pending
or active and remains locked throughout user imitation. Goal selection never
sends a motion frame and does not change Titan's demonstration sequence.

No clinical range-of-motion or treatment-effect claim is authorized by this implementation.
