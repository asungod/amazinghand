# OpenSignHand fixed mechanical demo — offline validation (2026-09-21)

## Scope and boundary

This record covers the new, fixed OpenSignHand mechanical demonstration path
between MaixCAM2 and Titan. It does **not** record a hardware pass. The hand has
not yet been moved by this firmware build.

- Supported recipe: protocol v1, `sequence_id=1` only.
- Motion: previously validated official close target, bounded hold, then the
  previously validated official open target.
- The request contains no servo IDs, positions, angles, speed or force values.
- The browser can only enqueue select/start/cancel intents. MaixCAM2 rechecks
  Titan link/status health and sends the fixed recipe after explicit human
  confirmation.
- Mechanical mode remains disabled unless sign mode and the separate
  `OPENSIGNHAND_MECHANICAL_DEMO=1` opt-in (or the equivalent marker file) are
  both present.
- The opt-in marker `maixcam2/opensignhand_mechanical.enable` was absent during
  this validation. Therefore this report does not authorize automatic motion.

The sequence is a competition demonstration candidate for a finite-vocabulary
training prototype. It is not evidence that the hand reproduces a standard
sign-language word.

## Implemented protocol contract

MaixCAM2 sends one of these fixed actions:

| Message | Meaning |
|---|---|
| `SIGN, version=1, action=1, sequence_id=1` | start fixed demonstration |
| `SIGN, version=1, action=2, sequence_id=1` | bounded cancel and open recovery |
| `SIGN, version=1, action=3, sequence_id=1` | return to verified open target |

Titan reports `SIGNSTAT` with protocol version, correlated UART request
sequence, recipe ID, state, result, completion count and last action. ACK=0
means queued/accepted only; only a terminal `SIGNSTAT` is completion authority.

Titan rejects unsupported versions, actions, argument counts and recipe IDs.
START/HOME require an already-online MaixCAM2 link. Link loss requests a bounded
cancel plus the verified open recovery. `TRAIN` and `SIGN` motion are mutually
exclusive.

## Host-side verification

Targeted Python suite:

```text
python -m unittest \
  smart_hand.tests.test_protocol \
  smart_hand.tests.test_sign_demo_contract \
  smart_hand.tests.test_sign_motion \
  smart_hand.tests.test_sign_integration \
  smart_hand.tests.test_maix_main -v

Ran 58 tests
OK
```

The C protocol parser was compiled with host GCC using `-std=c99 -Wall
-Wextra -Werror`; result: `C protocol tests passed`.

The repository-wide discovery run executed 477 tests. It produced 466 passes,
six pre-existing rehabilitation display-string assertion failures and five
pre-existing `host` import-path errors. None of the eleven failures exercises
the new `SIGN`/`SIGNSTAT` path. The targeted new path remained green.

## Titan Studio source synchronization

The following canonical files were copied to
`D:\Micu\RTTWorkspace\titan_uart_test\src` and verified byte-identical by
SHA-256:

| File | SHA-256 |
|---|---|
| `smart_hand_protocol.c` | `C354A06649574E3EF1344BCF7CE126F60AB2BFE4583A5CCC9BA5EEE09B7B6E3D` |
| `smart_hand_protocol.h` | `0DFDDA9AF4490CDBEC99D0D5940B9AA9F498CAD5931338D75699B83D8A11CF99` |
| `smart_hand_uart.c` | `247239B23FB037CFDD479F6ED3D6AEF8F4FF6FC80985FF423C248FC598707127` |
| `servo_bus_readonly_rt.c` | `4D67EB78D2DF00B0486E32C33FE325C4AC6813CECB5F4F130C56EF7B37403F73` |
| `servo_bus_readonly_rt.h` | `875A085ABA153DD5A1D372875A683FAF53275007FAD3B19E4BB647CD2C6586C0` |

The previous destination files and previous firmware artifacts were backed up
at:

```text
D:\Micu\RTTWorkspace\titan_uart_test\codex_backup_before_opensignhand_20260921_124923
```

## Real ARM build

The RT-Thread Studio GNU Arm 13.3 toolchain and the project's SCons build entry
completed successfully. This was a real Cortex-M85 firmware build, not a host
GCC substitute.

```text
SCONS_BUILD_EXIT=0
RAM   138228 / 1488 KB = 9.07%
FLASH 124700 / 1 MB    = 11.89%
text=123676, data=1024, bss=137200
```

One existing warning remained: the shell helper `sh_status` is compiled but
unused in this build configuration. No new source compilation or link error
was reported.

Firmware artifacts:

| Artifact | SHA-256 |
|---|---|
| `D:\Micu\RTTWorkspace\titan_uart_test\rtthread.elf` | `2A769C03457ED600BD2E205E7D53AB98FD9466628209A09B99401858E3C17D53` |
| `D:\Micu\RTTWorkspace\titan_uart_test\rtthread.hex` | `121262E133E6A54F3BAF7D32204FBABF52F6EDE367E4E00E9C165697E28DB016` |
| `D:\Micu\RTTWorkspace\titan_uart_test\rtthread.map` | `08CB1C44AF838E03484C353A3BCB98D1AC0998434631110F970167F966AF6D30` |

The map includes `process_sign_demo_request`, `servo_bus_sign_demo_request`
and `send_sign_status` from the production objects.

The generated CDT `Debug/makefile` also compiles historical backup directories
and therefore cannot currently produce a clean final link. The project SCons
entry excludes those backups and completed the production build above. Do not
represent the failed CDT-generated make attempt as a firmware failure.

## Required hardware validation (not yet run)

1. Flash the newly built firmware with MaixCAM2 and servo power disconnected.
2. Confirm normal Titan boot and UART2 listener; confirm no spontaneous motion.
3. Reconnect MaixCAM2 data lines and verify PING/STATUS/ACK with servo power still
   off.
4. With an operator at the power disconnect, connect the assembled hand and
   regulated servo supply.
5. Enable mechanical mode explicitly, select the single approved demonstration
   course, and click start once.
6. Observe exactly one close-hold-open sequence, then confirm open recovery,
   released torque, no abnormal sound, heat, collision or repeated motion.
7. Test cancel and link-loss recovery separately. Preserve Titan and Maix logs.

Until all seven steps pass, the mechanical sequence remains
`READY_FOR_BENCH_VALIDATION`, not `VALIDATED`.
