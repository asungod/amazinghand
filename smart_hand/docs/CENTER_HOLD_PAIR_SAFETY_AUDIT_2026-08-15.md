# CENTER_HOLD_PAIR_SAFETY_AUDIT_2026-08-15.md

**Author:** grokA (offline only)  
**Date:** 2026-08-15  
**Scope:** host/center_hold_scs0009_pair.py only. No production script modified.  
**Hardware access:** false (no COM port, no serial, no hardware probe).  

## 1. Production script hash (unchanged)
```
sha256: 57f4395ea1e50f81cd1d3385846d4e6645ad10debabe4de98cade2228ec1a5e5
size: 6794 bytes
```

## 2. Coverage of required protections
| Protection | Present in script? | Test in this batch? | Notes |
|-----------|--------------------|---------------------|-------|
| frame-mounted-confirmed flag | yes | yes | Refusal test passes |
| ID1/ID2 both pingable before motion | yes | yes | Missing-ID tests cover |
| Model check before motion | yes | yes | Unexpected-model test |
| Voltage 50-70 before motion | yes | yes | Overvoltage/undervoltage tests |
| Temperature <50°C before motion | yes | yes | Overtemp tests |
| 511 is electrical midpoint (no mechanical center) | yes | yes | Test name + constant check |
| Low speed (<=100) | yes | yes | Excessive-speed refusal |
| One missing servo = no motion | yes | yes | Missing-ID1/2 tests |
| Partial write on ID2 reference = abort | yes | yes | Short-write test |
| Timeout on ID2 reference = abort | yes | yes | Reference-timeout test |
| Hold status check every 5 s | yes | yes | Hold overtemp/voltage tests |
| Torque-off both IDs in finally | yes | yes | Torque-off failure test |
| No leftover torque on exit | yes | yes | Ctrl-C, missing-ID, overtemp tests |
| No production pose or calibration write | yes | yes | Import guard test |
| No ServoCommandGate or safety model | yes | yes | Production-pose guard test |

## 3. New behavior tests added
- `tests/test_center_hold_scs0009_pair_safety.py` (26 tests)
  - Happy path: start + 511 reference + hold + torque-off both
  - Missing ID1/2: no motion, no enable, torque-off both
  - Second servo enable failure: no motion for ID2, torque-off both
  - Partial reference write on ID2: abort
  - Reference timeout on ID2: abort
  - Hold overtemp/voltage: abort
  - Hold position drift: abort
  - Ctrl-C: torque-off both, exit 130
  - Excessive/zero speed: refusal (2)
  - Already-has-torque: refusal (1)
  - Unexpected model: refusal (1)
  - 511 outside limits: refusal (1)
  - No hardware access: true

## 4. Verdict
**All required protections present and exercised by offline behavior tests.**  
No production script touched. Tests can be run with `hardware_accessed=false`.  

Next step (Codex decision): approve or request patch. No further change in this batch.  
