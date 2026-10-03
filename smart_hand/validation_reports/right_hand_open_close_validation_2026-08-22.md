# Right-hand open/close validation — 2026-08-22

- Hardware accessed: true
- Hand: assembled JuxiTech AmazingHand right hand, eight SCS0009 servos
- Servo supply: vendor-provided regulated 5 V / 5 A adapter
- Control path: Titan UART1, 1,000,000 baud, black JuxiTech bus board
- Operator present with immediate 5 V disconnect available

## Verified mapping

| IDs | Official role | Operator-view physical finger |
|---|---|---|
| 1 / 2 | Index | third from left |
| 3 / 4 | Middle | second from left |
| 5 / 6 | Ring | leftmost |
| 7 / 8 | Thumb | thumb |

## Verified motion

1. Progressive open: PASS; observed `[337,684,334,688,337,682,333,688]` against `[332,690,332,690,332,690,332,690]`; operator confirmed normal.
2. Progressive close: PASS; observed `[756,264,756,269,756,265,689,332]` against `[758,264,758,264,758,264,690,332]`; operator confirmed normal.
3. Progressive reopen: PASS; observed `[338,682,337,688,338,681,332,691]`; returned to safe open posture.

All commands used 30-raw progressive steps. Feedback remained approximately 5.0–5.2 V and 24–25 C. Torque was released after every command. The Titan servo thread remained live after consecutive commands.

## Firmware defect fixed during validation

The first repeated command exposed an RT-Thread `_thread_timeout` assertion caused by a 1 ms timed semaphore wait racing with the UART receive ISR. The servo receive loop now uses bounded polling plus a 1 ms scheduler delay. Continuous RX drain loops are also byte-bounded. Local tests, ARM build, function-level linkage checks, and the three-command hardware sequence passed.

## Integrated STATUS validation

After flashing the calibrated build, Titan published a complete live servo snapshot (`published_count=8`, `ready=1`). With MaixCAM2 YOLO11 running, the UART link reported `sent=8`, `acked=8`, zero TX failures, rejects, malformed frames, timeouts, or UART RX errors. Titan STATUS was decoded as `link=ON`, `gate=DISARMED`, `submit=UNKNOWN`, and `pose=NO_ACTION`. The hand made no uncommanded movement. `vis=OFF` / `stale=1` in this sample means that no supported target was selected; it is not a servo-bus failure.

A real bottle was then presented to the camera. Before the validated eight-servo pose bank was enabled, Titan correctly reported `pose=NOT_CONFIGURED`; after the pose-bank migration and reflash, the same supported target reported `vis=ON`, `stale=0`, `act=CYLINDRICAL`, `reason=accepted`, and `pose=OK`. Intermittent low-confidence frames correctly reverted to `act=NONE` / `pose=NO_ACTION`. The link accumulated hundreds of acknowledged frames with zero TX failures, rejects, malformed frames, timeouts, or UART RX errors. Vision alone produced no hand motion.

## Explicit rehabilitation repetition validation

The debugger mailbox was used once as an explicit operator start input for the already validated rehabilitation sequence. Titan closed all eight servos, held the posture for approximately 1.5 seconds, automatically reopened the hand, released torque, and reported result `1` with completed count `1`. The operator confirmed the complete physical sequence was normal with no abnormal sound, heat, or motion.

The separate `TRAIN` request and MaixCAM2 touchscreen release-edge input were then deployed to both targets. Titan restarted with all eight live servo snapshots (`published_count=8`, `ready=1`), and the hand remained stationary during startup. The MaixCAM2 found `/dev/input/event1` and continued to exchange acknowledged UART frames with Titan.

The failure path was tested first: with no supported target selected, the display showed `vis=OFF`, `act=NONE`, and `TRAIN LOCKED`; pressing the locked area produced no hand motion. For the normal path, a real bottle was held in view and detected at 0.90 confidence. The display showed `vis=ON`, `stale=0`, `act=CYLINDRICAL`, `pose=OK`, and `START TRAIN`. One release-edge press on the physical MaixCAM2 display caused exactly one complete cycle: all fingers closed, held for approximately 1.5 seconds, and automatically reopened. The operator confirmed the sequence was complete and produced no abnormal sound. No repeated or uncommanded motion occurred.

## Authoritative TRAIN completion validation

The follow-up firmware added a separate outbound `TRAINSTAT` event without changing the frozen `STATUS` v1 arguments or the motion path. A physical-screen request produced the ordered Titan-authoritative states `TRAIN QUEUED`, `TRAIN RUNNING`, and `TRAIN COMPLETE`. The terminal reported a 17.923-second end-to-end repetition duration and Titan cumulative completion count `2`; Maix maintained 458/458 acknowledged request frames with zero TX failures, rejects, malformed frames, timeouts, or pending frames. The operator independently confirmed that the corresponding physical close-hold-open sequence was complete and had no abnormal sound or motion. The Maix display now presents a session-relative repetition count while retaining Titan's cumulative count internally.

## User-imitation vision validation

A separate MaixCAM2 hand-landmark probe was run with the hand base unpowered. The probe explicitly reported `uart_opened=false` and `motion=false`. The 21-point hand overlay tracked the operator's visible hand, classified the fully open posture as `OPEN` with score `1.00`, and counted six consecutive operator-performed open-close-open cycles. The terminal reported `USER REPETITION 1 COMPLETE` through `USER REPETITION 6 COMPLETE`. This validates basic repetition detection on the current camera and operator under the observed lighting; it does not yet establish clinical range of motion, exercise quality, or performance for other users and backgrounds.

## Integrated rehabilitation-session software validation

The deployed combined project completed the intended software sequence without a process restart: supported-target mode, explicit Titan training request, ordered authoritative `TRAIN QUEUED` / `TRAIN RUNNING` / `TRAIN COMPLETE REP=1 17.9s`, hand-landmark imitation mode, five counted user open-close-open repetitions, hand-model release, and YOLO target-mode restoration. During imitation the terminal explicitly reported `motion request disabled`, while Titan authority showed no actionable vision request. The UART link reached 160 sent and 160 acknowledged frames with zero TX failures, rejects, unexpected frames, malformed frames, timeouts, or pending frames. The captured log SHA-256 is `BB564ADFA03A709FD61EB90F78A60A39EDB9C7831522DA1732D0474D8E4F51A8`.

This validates the integrated software and model-resource transition. The operator subsequently confirmed that the robot demonstration in this exact run completed normally. This physical result was operator-observed and is not inferred from `TRAIN COMPLETE` alone.

The first result-page hardware run then completed five user repetitions in 20.460 seconds (4.092 seconds average), reported 100% completion, restored YOLO target mode, and continued through 140/140 acknowledged frames with zero link or UART errors. Evidence log SHA-256: `1B634FEF172EFBA378B2154E2FA102640078CEE33FF1BFC9BFBDB07B4DB4650A`.

The first persistent-history hardware run completed five user repetitions in 20.437 seconds (4.087 seconds average) after a 17.8-second Titan demonstration. Exactly one append was reported as `USER SESSION SAVED session=1 path=/root/smart_hand_rehab_sessions.csv`; YOLO target mode was restored and the link continued through 106/106 acknowledged frames with zero errors. Evidence log SHA-256: `D124FC71E9303B0A61F2CBC1B4DEFA491143A4E8A180A60363971A874000EC67`.

The device CSV was subsequently read back without modification and reproduced locally as `outputs/smart_hand_rehab_sessions_2026-08-22.csv` (SHA-256 `0E0C395DC83CA82AAA6C72E7D1053863EF56E63C60CC45B002AE9F637DAEC618`). The validated host generator produced `outputs/smart_hand_rehab_report_2026-08-22.html` (SHA-256 `E18AF5CF3022E327258D0E27287FF62FDA42304DC6478D5375CA1F3C9B6B2832`) showing one completed session, five repetitions, 100% completion, 20.4-second imitation time, 4.1-second average repetition time, and 17.8-second demonstration time.

A second intentionally slower session was appended as session 2 without replacing session 1. It also completed 5/5 at 100%, with a 17.956-second demonstration, 46.075-second imitation duration, and 9.215-second average repetition time. This validates monotonic multi-session persistence and gives the trend report two distinguishable timing samples; it is not interpreted as clinical improvement or decline.

The hardware timeout path was then exercised by withholding all user imitation after a normal Titan demonstration. MaixCAM2 reported `outcome=TIMEOUT`, `reps=0`, `goal=5`, `duration_ms=60009.0`, `completion_pct=0`, and `avg_rep_ms=-1`, then appended exactly one `session=3` record. No user repetitions were falsely counted. The hand model was released, YOLO target mode was restored, and the link reached 168/168 acknowledged frames with zero TX failures, rejects, unexpected or malformed frames, timeouts, pending frames, UART RX errors, or vision read errors. The operator confirmed that the hand made no repeated movement and produced no abnormal sound or heat during the 60-second waiting interval. Evidence log SHA-256: `D4E69FC482D3E4EB6B75E067A568DA4B79AE8C5C36D2B73432DC475AE627028E`.

Readback of the device CSV confirmed that session 3 persisted as `1,3,TIMEOUT,0,5,0,17733,60009,-1`, while both earlier COMPLETE records remained intact. The host report accepted the three-row schema and rendered the timeout as a zero-percent incomplete session rather than a pass.

The configurable goal selector was then exercised in target idle mode. The
MaixCAM2 log reported `USER GOAL CHANGED goal=10`, `15`, `5`, and `10` in
order, confirming release-edge cycling and persistence of the final selected
goal. No TRAIN frame or motion command was generated during selection; UART
remained 108/108 acknowledged with zero failures, rejects, malformed frames,
timeouts, or pending frames. Evidence came from the captured target-phase run
and is software/input validation only.

## Boundary

These results approve the eight ID/direction rows, the observed open/close soft bounds, a maximum 30-raw command step, live eight-servo telemetry, STATUS reporting, the fail-closed touchscreen gate, one explicitly requested no-object-contact rehabilitation repetition through the deployed MaixCAM2-to-Titan path, and basic user open-close-open repetition counting in a separate vision-only probe. They do not approve object-contact force control, unattended operation, clinical range-of-motion claims, or camera-triggered automatic motion. Visual detections remain advisory; only a separate explicit physical-screen training request may queue the fixed rehabilitation repetition.
