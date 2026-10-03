# MaixCAM2 YOLO11 -> Titan UART2 long-run acceptance (2026-08-15)

Status: `REAL_HARDWARE_NO_SERVO_ACCEPTED`

## Scope

This report records the user-operated real-hardware run of the MaixCAM2 camera,
YOLO11 target selection, UART2 link, Titan sequence handling, ACK path, and grip
policy mapping. The servo bus and servo power remained outside this test.

This is not evidence for servo motion, mechanical limits, calibrated poses, or a
complete finger grasp.

## Hardware boundary

- MaixCAM2 and Titan Mini were independently powered.
- The verified H1 three-wire UART2 connection was used: GND, crossed TX, crossed RX.
- No VCC wire was connected between the boards.
- Servos and the servo power bus were disconnected.
- Maix entry point: `maixcam2/main.py`, `VISION_MODE="yolo11"`.
- Titan firmware listened on `uart2`; UART1 remained the diagnostic console.

## Functional evidence

The real camera detected COCO bottle class 39. Titan UART1 printed:

```text
smart_hand: vision link ONLINE
VISION ... class=39 conf=75 action=CYLINDRICAL_GRASP reason=accepted pose=NOT_CONFIGURED actionable=0
```

The confidence gate also rejected a real low-confidence observation:

```text
VISION ... class=39 conf=63 action=NO_ACTION reason=low_confidence pose=NO_ACTION actionable=0
```

This proves the real-camera class reached Titan policy handling. It also proves
the configured safety boundary remained active: no pose was configured and no
physical action was authorized.

The user removed the bottle and returned it. Maix target statistics changed from
`lost=1 active=0` to `acquired=2 active=1`, while ACK traffic continued with
`timeout=0`.

## USB/RNDIS recovery

With full-rate preview, Windows logged NDIS event 10400 for `Remote NDIS
Compatible Device`: the driver reset the interface because the hardware stopped
responding. The Type-C cable remained connected and UART2 traffic before each
reset was error-free.

The production entry point was changed to:

```python
VISION_PROCESS_INTERVAL_MS = 50
PREVIEW_INTERVAL_MS = 500
```

This keeps camera/NPU target processing at up to 20 FPS and limits the
MaixVision/USB preview path to 2 FPS. The UART PING interval (1000 ms), VISION
send interval (500 ms), ACK timeout (1000 ms), and target stale timeout (750 ms)
were not changed.

After this change, Windows showed no new matching NDIS reset event during the
checked 30-minute window.

## Long-run result

The final captured run continued from sequence 0 through at least sequence 2770.
Because the configured maximum transmission rate is one PING per second plus two
VISION messages per second, this sequence count represents at least about 15
minutes 23 seconds of continuous operation.

Representative complete statistics near the end of the run:

```text
link stats: sent=2748 tx_fail=0 acked=2748 rejected=0 unexpected=0 malformed=0 timeout=0 consecutive_timeout=0 max_consecutive_timeout=0 pending=0 rtt_last_ms=17.0 rtt_avg_ms=28.0 rtt_max_ms=138.0
uart stats: rx_errors=0
vision stats: mode=yolo11 frames=13689 detections=28806 selected=11361 no_target=2328 infer_last_ms=7.0 infer_avg_ms=10.0 infer_max_ms=36.0 infer_fps=100.0 read_errors=0
```

The transcript then continued with successful ACKs through sequence 2770.

## Acceptance decision

Accepted for the following scope:

- real MaixCAM2 camera and YOLO11 inference;
- supported-class filtering for bottle/cup/remote;
- target acquire, loss, and reacquire behavior;
- MaixCAM2 UART2 to Titan H1 message transport;
- Titan ACK, sequence progression, policy mapping, and confidence rejection;
- stable USB/RNDIS debugging after preview throttling;
- no-servo long-run communication.

Not accepted or not attempted:

- servo command execution from Titan;
- frame-mounted servo readback or motion in this run;
- horn/link installation;
- mechanical direction, center, or soft limits;
- production pose-bank values;
- complete finger or complete hand grasping.

## Current mechanical dependency

The user reports that the two servos are already installed in the finger frame.
The horns and linkage are not installed. One M2x18 threaded rod is still in
transit and is expected after about two days, so linkage assembly remains paused.

