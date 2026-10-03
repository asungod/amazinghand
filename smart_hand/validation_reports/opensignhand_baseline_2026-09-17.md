# OpenSignHand implementation baseline (2026-09-17)

This record freezes the four existing MaixCAM2 integration files before the
OpenSignHand MVP is added. Git remains the authoritative rollback source; this
file records the exact pre-change content hashes used by the implementation
review.

| File | SHA-256 |
|---|---|
| `smart_hand/maixcam2/main.py` | `77b25050c9974561e79fcf21f47fd4d85da6019c91f72193a9e928e396d8fc0a` |
| `smart_hand/maixcam2/rehab_hand_source.py` | `d05073957e990898041fbf3aaa1e01247c0c585737326c42b0614370aa020397` |
| `smart_hand/maixcam2/live_sidecar.py` | `c934d068a674a4e251202ac1e6c51efb9b8fd8c9c696b8ff491764bc60990542` |
| `smart_hand/maixcam2/web_stream.py` | `3b940578406730104b31e2c2ddcb085952f2e676ca957063384ce9a934a1ac96` |

## Focused pre-change test result

Command:

```powershell
python -m unittest `
  smart_hand.tests.test_hand_rehab_tracker `
  smart_hand.tests.test_rehab_imitation `
  smart_hand.tests.test_rehab_session_log `
  smart_hand.tests.test_maix_main `
  smart_hand.tests.test_live_sidecar `
  smart_hand.tests.test_web_stream -v
```

Result: 78 tests ran, 72 passed, 6 existing failures were confined to
`test_rehab_imitation.py`. Those six assertions expect the older verbose
quality/result wording, while the current implementation emits the compact
`Q:/P:/H:` display wording. OpenSignHand work must not modify the existing
rehabilitation controller or its tests merely to hide this baseline mismatch.

## Safety boundary

- Existing UART frames, CRC/ACK handling, Titan state checks, servo parameters,
  and rehabilitation CSV schemas are outside the OpenSignHand change scope.
- New sign-training behavior is opt-in and must remain disabled by default until
  bench validation is completed.
- A web or local request may enqueue an intent only. The MaixCAM2 main loop must
  re-check link freshness, state, and explicit user confirmation before any
  hardware command is submitted.
