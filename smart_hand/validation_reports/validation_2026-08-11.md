# Smart Hand Local Validation Report

- Generated: `2026-08-11T01:34:21+08:00`
- Result: `PASS`
- Host: `Windows-10-10.0.22631-SP0`
- Python: `3.11.7 | packaged by Anaconda, Inc. | (main, Dec 15 2023, 18:05:47) [MSC v.1916 64 bit (AMD64)]`
- Repository mode: local files only; no Git or network action performed
- Studio project checked: `D:\Micu\RTTWorkspace\titan_uart_test`

## Command

```powershell
pwsh -File host\run_all_checks.ps1
```

## Maix Application Hashes

| File | Bytes | SHA-256 |
|---|---:|---|
| `main.py` | 5834 | `C6AD7C9CE2DFE1E9718E2DDA5A70ED0DD1D45EDA5F00EE44B243D1537DE3F7D1` |
| `protocol.py` | 4330 | `9A48340B4C3FF9EC25EB5A0589437FE7939B2DFA6F1265753B6C4739541D0864` |
| `link_monitor.py` | 3557 | `AB0546B453D29283C0A27875F2F6C4F044945E9B0171DA52D89F4FF1EF7F8F3D` |
| `target_tracker.py` | 6104 | `53FC5694DB65DA2824CE20E17A5F9A542EAA45EDD111D9D439961C7E0A52D32C` |
| `vision_source.py` | 7603 | `3EAA52C475C938251D7702C3B942DB532308CD745332FEBF0AF95010182C22E9` |

## Titan Canonical Hashes

| File | Bytes | SHA-256 |
|---|---:|---|
| `smart_hand_protocol.c` | 5686 | `4165253F25B752714977A2E5DCADC5E9F75F8DF5791CBC4217171E2C07C07C90` |
| `smart_hand_protocol.h` | 1000 | `544892049456D589CE43B77A347F08E6C5D5717AFC27F8CBFE4B200183FFE1D3` |
| `smart_hand_uart.c` | 9248 | `B6D408EB7E225E2FCC22DD92D434697C9FF1156EE3B3F8D40604314E44182D5C` |

## Titan Studio Hashes

| File | Bytes | SHA-256 |
|---|---:|---|
| `smart_hand_protocol.c` | 5686 | `4165253F25B752714977A2E5DCADC5E9F75F8DF5791CBC4217171E2C07C07C90` |
| `smart_hand_protocol.h` | 1000 | `544892049456D589CE43B77A347F08E6C5D5717AFC27F8CBFE4B200183FFE1D3` |
| `smart_hand_uart.c` | 9248 | `B6D408EB7E225E2FCC22DD92D434697C9FF1156EE3B3F8D40604314E44182D5C` |

## Check Output

```text
[1/6] Python unit and stress tests
[2/6] Python syntax checks
[3/6] Maix deployment preflight
Maix config: mode=mock uart=/dev/ttyS4 baud=115200 process_ms=0 send_ms=500 stable_frames=3 stale_ms=750 match_iou=0.2
Required Maix application files:
C6AD7C9CE2DFE1E9718E2DDA5A70ED0DD1D45EDA5F00EE44B243D1537DE3F7D1  main.py  5834 bytes
9A48340B4C3FF9EC25EB5A0589437FE7939B2DFA6F1265753B6C4739541D0864  protocol.py  4330 bytes
AB0546B453D29283C0A27875F2F6C4F044945E9B0171DA52D89F4FF1EF7F8F3D  link_monitor.py  3557 bytes
53FC5694DB65DA2824CE20E17A5F9A542EAA45EDD111D9D439961C7E0A52D32C  target_tracker.py  6104 bytes
3EAA52C475C938251D7702C3B942DB532308CD745332FEBF0AF95010182C22E9  vision_source.py  7603 bytes
MAIX DEPLOY PREFLIGHT PASSED
[4/6] Host communication demo
Maix TX: $PING,1*F692
Titan RX: {'type': 'PING', 'seq': 1, 'args': []}
Titan RX: {'type': 'VISION', 'seq': 2, 'args': [3, 320, 240, 80, 120, 96]}
Maix RX: {'type': 'ACK', 'seq': 1, 'args': [0]}
Maix RX: {'type': 'ACK', 'seq': 2, 'args': [0]}

Injecting one corrupted frame, then a valid frame...
Titan RX: {'type': 'PING', 'seq': 4, 'args': []}
Recovered ACKs: [{'type': 'ACK', 'seq': 4, 'args': [0]}]
Demo passed
[5/6] C parser build and tests
C protocol tests passed
[6/6] Titan canonical/Studio source sync

File                  Match CanonicalSHA256                                                  StudioSHA256
----                  ----- ---------------                                                  ------------
smart_hand_protocol.c  True 4165253F25B752714977A2E5DCADC5E9F75F8DF5791CBC4217171E2C07C07C90 4165253F25B752714977A2E5D…
smart_hand_protocol.h  True 544892049456D589CE43B77A347F08E6C5D5717AFC27F8CBFE4B200183FFE1D3 544892049456D589CE43B77A3…
smart_hand_uart.c      True B6D408EB7E225E2FCC22DD92D434697C9FF1156EE3B3F8D40604314E44182D5C B6D408EB7E225E2FCC22DD92D…

Titan source sync check passed.
ALL LOCAL CHECKS PASSED
test_duplicate_old_sequence_and_rollover_are_handled (test_action_safety_model.MotionSafetyGateTests.test_duplicate_old_sequence_and_rollover_are_handled) ... ok
test_fault_is_latched_and_requires_new_arm_and_target (test_action_safety_model.MotionSafetyGateTests.test_fault_is_latched_and_requires_new_arm_and_target) ... ok
test_link_loss_disarms_clears_target_and_requests_safe_stop (test_action_safety_model.MotionSafetyGateTests.test_link_loss_disarms_clears_target_and_requests_safe_stop) ... ok
test_stale_target_requests_safe_stop (test_action_safety_model.MotionSafetyGateTests.test_stale_target_requests_safe_stop) ... ok
test_startup_blocks_until_link_arm_and_fresh_target (test_action_safety_model.MotionSafetyGateTests.test_startup_blocks_until_link_arm_and_fresh_target) ... ok
test_mock_mode_ten_minute_accelerated_schedule (test_maix_main.MaixMainIntegrationTests.test_mock_mode_ten_minute_accelerated_schedule) ... ok
test_mock_target_sends_ping_then_rate_limited_vision (test_maix_main.MaixMainIntegrationTests.test_mock_target_sends_ping_then_rate_limited_vision) ... ok
test_no_target_keeps_ping_without_vision (test_maix_main.MaixMainIntegrationTests.test_no_target_keeps_ping_without_vision) ... ok
test_uart_read_error_is_reported_without_stopping_transmission (test_maix_main.MaixMainIntegrationTests.test_uart_read_error_is_reported_without_stopping_transmission) ... ok
test_vision_initialization_failure_degrades_to_ping_only (test_maix_main.MaixMainIntegrationTests.test_vision_initialization_failure_degrades_to_ping_only) ... ok
test_ack_resets_consecutive_timeout_count (test_protocol.AckMonitorTests.test_ack_resets_consecutive_timeout_count) ... ok
test_acknowledged_and_rejected_frames (test_protocol.AckMonitorTests.test_acknowledged_and_rejected_frames) ... ok
test_full_write_is_tracked (test_protocol.AckMonitorTests.test_full_write_is_tracked) ... ok
test_partial_and_exception_writes_are_not_tracked (test_protocol.AckMonitorTests.test_partial_and_exception_writes_are_not_tracked) ... ok
test_timeout_and_unexpected_ack_are_counted (test_protocol.AckMonitorTests.test_timeout_and_unexpected_ack_are_counted) ... ok
test_crc_error_is_dropped_and_next_frame_recovers (test_protocol.ProtocolTests.test_crc_error_is_dropped_and_next_frame_recovers) ... ok
test_fragmented_stream (test_protocol.ProtocolTests.test_fragmented_stream) ... ok
test_garbage_before_header_is_ignored (test_protocol.ProtocolTests.test_garbage_before_header_is_ignored) ... ok
test_new_header_recovers_unterminated_frame (test_protocol.ProtocolTests.test_new_header_recovers_unterminated_frame) ... ok
test_oversized_unterminated_input_recovers (test_protocol.ProtocolTests.test_oversized_unterminated_input_recovers) ... ok
test_round_trip (test_protocol.ProtocolTests.test_round_trip) ... ok
test_unknown_type_and_too_many_args_are_rejected (test_protocol.ProtocolTests.test_unknown_type_and_too_many_args_are_rejected) ... ok
test_unsigned_ranges_are_enforced (test_protocol.ProtocolTests.test_unsigned_ranges_are_enforced) ... ok
test_oversized_unterminated_chunk_does_not_remain_buffered (test_protocol_stress.ProtocolStressTests.test_oversized_unterminated_chunk_does_not_remain_buffered) ... ok
test_random_chunk_boundaries_preserve_all_frames (test_protocol_stress.ProtocolStressTests.test_random_chunk_boundaries_preserve_all_frames) ... ok
test_random_noise_and_corruption_recover_to_valid_frame (test_protocol_stress.ProtocolStressTests.test_random_noise_and_corruption_recover_to_valid_frame) ... ok
test_all_json_vectors_match_reference_model (test_session_sequence_model.SessionSequenceModelTests.test_all_json_vectors_match_reference_model) ... ok
test_rejects_out_of_range_fields (test_session_sequence_model.SessionSequenceModelTests.test_rejects_out_of_range_fields) ... ok
test_different_target_switches_only_after_stability (test_target_tracker.TargetTrackerTests.test_different_target_switches_only_after_stability) ... ok
test_invalid_observation_does_not_become_active (test_target_tracker.TargetTrackerTests.test_invalid_observation_does_not_become_active) ... ok
test_iou_requires_same_class (test_target_tracker.TargetTrackerTests.test_iou_requires_same_class) ... ok
test_matching_active_target_updates_immediately (test_target_tracker.TargetTrackerTests.test_matching_active_target_updates_immediately) ... ok
test_requires_consecutive_stable_frames (test_target_tracker.TargetTrackerTests.test_requires_consecutive_stable_frames) ... ok
test_short_dropout_is_tolerated_then_target_expires (test_target_tracker.TargetTrackerTests.test_short_dropout_is_tolerated_then_target_expires) ... ok
test_zero_iou_threshold_still_requires_same_class (test_target_tracker.TargetTrackerTests.test_zero_iou_threshold_still_requires_same_class) ... ok
test_dropout_is_retained_then_expires_before_later_send (test_target_tracker.VisionSchedulerTests.test_dropout_is_retained_then_expires_before_later_send) ... ok
test_elapsed_callback_handles_tick_wraparound (test_target_tracker.VisionSchedulerTests.test_elapsed_callback_handles_tick_wraparound) ... ok
test_processing_interval_is_independent_from_send_interval (test_target_tracker.VisionSchedulerTests.test_processing_interval_is_independent_from_send_interval) ... ok
test_stable_target_waits_for_send_boundary (test_target_tracker.VisionSchedulerTests.test_stable_target_waits_for_send_boundary) ... ok
test_all_generated_cases_match_expected_parser_results (test_uart_fault_corpus.UartFaultCorpusTests.test_all_generated_cases_match_expected_parser_results) ... ok
test_serialization_is_deterministic (test_uart_fault_corpus.UartFaultCorpusTests.test_serialization_is_deterministic) ... ok
test_written_corpus_round_trips_and_revalidates (test_uart_fault_corpus.UartFaultCorpusTests.test_written_corpus_round_trips_and_revalidates) ... ok
test_hash_record_reports_digest_and_missing_file (test_validation_report.ValidationReportTests.test_hash_record_reports_digest_and_missing_file) ... ok
test_report_marks_failure_and_strips_ansi_sequences (test_validation_report.ValidationReportTests.test_report_marks_failure_and_strips_ansi_sequences) ... ok
test_example_covers_acquire_switch_dropout_and_loss (test_vision_replay.VisionReplayTests.test_example_covers_acquire_switch_dropout_and_loss) ... ok
test_extracts_replay_rows_from_mixed_probe_log (test_vision_replay.VisionReplayTests.test_extracts_replay_rows_from_mixed_probe_log) ... ok
test_rejects_decreasing_timestamps (test_vision_replay.VisionReplayTests.test_rejects_decreasing_timestamps) ... ok
test_allowed_class_filter_is_applied (test_vision_source.VisionPolicyTests.test_allowed_class_filter_is_applied) ... ok
test_box_is_clipped_to_frame (test_vision_source.VisionPolicyTests.test_box_is_clipped_to_frame) ... ok
test_center_breaks_equal_confidence_tie_before_area (test_vision_source.VisionPolicyTests.test_center_breaks_equal_confidence_tie_before_area) ... ok
test_highest_confidence_detection_is_selected (test_vision_source.VisionPolicyTests.test_highest_confidence_detection_is_selected) ... ok
test_invalid_or_outside_boxes_are_ignored (test_vision_source.VisionPolicyTests.test_invalid_or_outside_boxes_are_ignored) ... ok
test_larger_box_breaks_equal_confidence_tie (test_vision_source.VisionPolicyTests.test_larger_box_breaks_equal_confidence_tie) ... ok
test_minimum_score_is_enforced (test_vision_source.VisionPolicyTests.test_minimum_score_is_enforced) ... ok
test_mock_source_is_deterministic (test_vision_source.VisionPolicyTests.test_mock_source_is_deterministic) ... ok
test_replay_rows_format_target_and_no_target (test_vision_source.VisionPolicyTests.test_replay_rows_format_target_and_no_target) ... ok
test_yolo_source_uses_documented_maix_api_shape (test_vision_source.VisionPolicyTests.test_yolo_source_uses_documented_maix_api_shape) ... ok
test_parameter_list_deduplicates_and_rejects_out_of_range (test_vision_sweep.VisionParameterSweepTests.test_parameter_list_deduplicates_and_rejects_out_of_range) ... ok
test_sweep_reports_acquisition_latency_for_each_combination (test_vision_sweep.VisionParameterSweepTests.test_sweep_reports_acquisition_latency_for_each_combination) ... ok
test_replay_mode_prints_header_target_and_none_rows (test_yolo_probe.YoloProbeIntegrationTests.test_replay_mode_prints_header_target_and_none_rows) ... ok

----------------------------------------------------------------------
Ran 60 tests in 0.500s

OK
```
