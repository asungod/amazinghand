# TRAINSTAT completion telemetry — 2026-08-22

`TRAINSTAT` is Titan-to-Maix telemetry for an explicitly accepted `TRAIN`
request. It does not replace `ACK`, does not alter the frozen eight-argument
`STATUS` v1 frame, and never triggers motion.

Frame arguments (version 1):

1. `ver`: `1`
2. `request_seq`: sequence of the corresponding inbound `TRAIN`
3. `state`: `1=QUEUED`, `2=RUNNING`, `3=SUCCEEDED`, `4=FAILED`
4. `result_code`: Titan servo result (`1` is complete; other nonzero values
   preserve the existing recovery/failure meanings)
5. `completed_count`: Titan-authoritative successful repetitions since boot

Titan emits a frame when the state or result changes. Maix accepts a frame only
when its version and `request_seq` match the active request. A missing terminal
frame times out fail-closed; Maix must not infer completion from elapsed time.

Compatibility: an older Maix parser drops the unknown outbound frame but still
receives the original `ACK`. An updated Maix never treats `TRAINSTAT` as an ACK
and therefore cannot close PING/VISION pending entries with it.
