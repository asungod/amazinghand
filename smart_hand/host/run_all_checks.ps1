param(
    [string]$StudioProject = 'D:\Micu\RTTWorkspace\titan_uart_test'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

function Assert-NativeSuccess {
    param([string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

Push-Location $projectRoot
try {
    Write-Host '[1/8] Python unit and stress tests'
    & python -m unittest discover -s tests -v
    Assert-NativeSuccess 'Python tests'

    Write-Host '[2/8] Python syntax checks'
    & python -m py_compile `
        maixcam2\main.py `
        maixcam2\protocol.py `
        maixcam2\link_monitor.py `
        maixcam2\target_tracker.py `
        maixcam2\vision_source.py `
        maixcam2\status_snapshot.py `
        maixcam2\rehab_train.py `
        maixcam2\rehab_imitation.py `
        maixcam2\rehab_quality.py `
        maixcam2\rehab_session_log.py `
        maixcam2\rehab_hand_source.py `
        maixcam2\rehab_goal.py `
        maixcam2\hand_rehab_tracker.py `
        maixcam2\print_rehab_sessions.py `
        maixcam2\hand_landmarks_probe.py `
        maixcam2\hand_landmarks_probe_single_file.py `
        maixcam2\time_api_probe.py `
        maixcam2\yolo_probe.py `
        maixcam2\yolo_probe_single_file.py `
        maixcam2\uart2_loopback_probe_single_file.py `
        host\check_maix_deploy.py `
        host\create_validation_report.py `
        host\generate_rehab_session_report.py `
        host\generate_uart_fault_corpus.py `
        host\action_safety_model.py `
        host\analyze_servo_log.py `
        host\center_hold_scs0009_pair.py `
       host\execution_state_model.py `
       host\eight_servo_group_stop_model.py `
        host\eight_servo_plan_model.py `
       host\four_finger_config_rules.py `
        host\four_finger_bringup_rules.py `
        host\finger_smoke_scs0009.py `
        host\grip_policy_model.py `
        host\nudge_scs0009.py `
        host\probe_scs0009.py `
        host\replay_vision.py `
        host\run_offline_rehearsal.py `
        host\session_sequence_model.py `
        host\servo_safety_model.py `
        host\set_scs0009_id.py `
        host\sweep_vision_params.py `
        host\sync_nudge_scs0009_pair.py `
        host\run_demo.py `
        tests\test_action_safety_model.py `
        tests\test_analyze_servo_log.py `
        tests\test_dashboard_asset.py `
       tests\test_execution_state_model.py `
        tests\test_eight_servo_group_stop_model.py `
        tests\test_eight_servo_plan_model.py `
       tests\test_four_finger_config_rules.py `
        tests\test_four_finger_bringup_rules.py `
        tests\test_grip_policy_model.py `
        tests\test_maix_main.py `
        tests\test_offline_rehearsal.py `
        tests\test_protocol.py `
        tests\test_rehab_train.py `
        tests\test_rehab_imitation.py `
        tests\test_rehab_quality.py `
        tests\test_rehab_goal.py `
        tests\test_rehab_session_log.py `
        tests\test_hand_rehab_tracker.py `
        tests\test_protocol_stress.py `
        tests\test_session_sequence_model.py `
        tests\test_servo_safety_model.py `
        tests\test_target_tracker.py `
        tests\test_uart_fault_corpus.py `
        tests\test_validation_report.py `
        tests\test_generate_rehab_session_report.py `
        tests\test_vision_replay.py `
        tests\test_vision_sweep.py `
        tests\test_vision_source.py `
        tests\test_yolo_probe.py `
        host\titan_linkage_check.py `
        host\no_servo_uart_acceptance.py `
        host\accept_uart_frame.py `
        host\titan_uart_acceptance.py `
        host\uart_segment_probe.py `
        host\titan_linkage_check.py `
        tests\test_titan_linkage_check.py `
        tests\test_no_servo_uart_acceptance.py `
        tests\test_titan_uart_acceptance.py `
        tests\test_uart_segment_probe.py
    Assert-NativeSuccess 'Python syntax checks'

    Write-Host '[3/8] Maix deployment preflight'
    & python host\check_maix_deploy.py
    Assert-NativeSuccess 'Maix deployment preflight'

    Write-Host '[4/8] Host communication demo'
    & python host\run_demo.py
    Assert-NativeSuccess 'Host communication demo'
    Write-Host '[4b/8] Legacy UART parser acceptance toolkit (motion proof retired)'
    & python host\no_servo_uart_acceptance.py
    Assert-NativeSuccess 'UART parser acceptance toolkit'
    & python host\titan_uart_acceptance.py --dry-run
    Assert-NativeSuccess 'Titan UART acceptance dry-run'
    & python host\uart_segment_probe.py --dry-run
    Assert-NativeSuccess 'UART segment probe dry-run'
    & python maixcam2\uart2_loopback_probe_single_file.py
    Assert-NativeSuccess 'Maix UART2 loopback probe PC dry-run'

    Write-Host '[5/8] C parser build and tests'
    & gcc -std=c99 -Wall -Wextra -Werror `
        -Ititan_rtthread `
        tests\test_protocol_c.c `
        titan_rtthread\smart_hand_protocol.c `
        -o tests\test_protocol_c.exe
    Assert-NativeSuccess 'C parser build'
    & .\tests\test_protocol_c.exe
    Assert-NativeSuccess 'C parser tests'

    Write-Host '[6/8] SCS0009 packet codec build and tests'
    & gcc -std=c99 -Wall -Wextra -Werror `
        -Ititan_rtthread `
        tests\test_scs0009_packet_c.c `
        titan_rtthread\scs0009_packet.c `
        -o tests\test_scs0009_packet_c.exe
    Assert-NativeSuccess 'SCS0009 packet codec build'
    & .\tests\test_scs0009_packet_c.exe
    Assert-NativeSuccess 'SCS0009 packet codec tests'
    & gcc -std=c99 -Wall -Wextra -Werror `
        -Ititan_rtthread `
        tests\test_scs0009_stream_c.c `
        titan_rtthread\scs0009_stream.c `
        titan_rtthread\scs0009_packet.c `
        -o tests\test_scs0009_stream_c.exe
    Assert-NativeSuccess 'SCS0009 stream parser build'
    & .\tests\test_scs0009_stream_c.exe
    Assert-NativeSuccess 'SCS0009 stream parser tests'
    & gcc -std=c99 -Wall -Wextra -Werror `
        -Ititan_rtthread `
        tests\test_scs0009_transaction_c.c `
        titan_rtthread\scs0009_transaction.c `
        titan_rtthread\scs0009_stream.c `
        titan_rtthread\scs0009_packet.c `
        -o tests\test_scs0009_transaction_c.exe
    Assert-NativeSuccess 'SCS0009 transaction build'
    & .\tests\test_scs0009_transaction_c.exe
    Assert-NativeSuccess 'SCS0009 transaction tests'

    Write-Host '[7/8] Servo safety gate C build and tests'
    & gcc -std=c99 -Wall -Wextra -Werror `
        -Ititan_rtthread `
        tests\test_servo_safety_gate_c.c `
        titan_rtthread\servo_safety_gate.c `
        titan_rtthread\scs0009_packet.c `
        -o tests\test_servo_safety_gate_c.exe
    Assert-NativeSuccess 'Servo safety gate C build'
    & .\tests\test_servo_safety_gate_c.exe
    Assert-NativeSuccess 'Servo safety gate C tests'
    & gcc -std=c99 -Wall -Wextra -Werror `
        -Ititan_rtthread `
        tests\test_eight_servo_safety_gate_c.c `
        titan_rtthread\eight_servo_safety_gate.c `
        titan_rtthread\scs0009_packet.c `
        -o tests\test_eight_servo_safety_gate_c.exe
    Assert-NativeSuccess 'Eight-servo safety gate C build'
    & .\tests\test_eight_servo_safety_gate_c.exe
    Assert-NativeSuccess 'Eight-servo safety gate C tests'
    & gcc -std=c99 -Wall -Wextra -Werror `
        -Ititan_rtthread `
        tests\test_eight_servo_pose_bank_c.c `
        titan_rtthread\eight_servo_pose_bank.c `
        -o tests\test_eight_servo_pose_bank_c.exe
    Assert-NativeSuccess 'Eight-servo pose bank C build'
    & .\tests\test_eight_servo_pose_bank_c.exe
    Assert-NativeSuccess 'Eight-servo pose bank C tests'
    & gcc -std=c99 -Wall -Wextra -Werror `
        -Ititan_rtthread `
        tests\test_servo_motion_monitor_c.c `
        titan_rtthread\servo_motion_monitor.c `
        -o tests\test_servo_motion_monitor_c.exe
    Assert-NativeSuccess 'Servo motion monitor C build'
    & .\tests\test_servo_motion_monitor_c.exe
    Assert-NativeSuccess 'Servo motion monitor C tests'
    & gcc -std=c99 -Wall -Wextra -Werror `
        -Ititan_rtthread `
        tests\test_grip_policy_c.c `
        titan_rtthread\grip_policy.c `
        -o tests\test_grip_policy_c.exe
    Assert-NativeSuccess 'Grip policy C build'
    & .\tests\test_grip_policy_c.exe
    Assert-NativeSuccess 'Grip policy C tests'
    & gcc -std=c99 -Wall -Wextra -Werror `
        -Ititan_rtthread `
        tests\test_grip_pose_bank_c.c `
        titan_rtthread\grip_pose_bank.c `
        titan_rtthread\grip_policy.c `
        titan_rtthread\servo_safety_gate.c `
        -o tests\test_grip_pose_bank_c.exe
    Assert-NativeSuccess 'Grip pose bank C build'
    & .\tests\test_grip_pose_bank_c.exe
    Assert-NativeSuccess 'Grip pose bank C tests'
    & gcc -std=c99 -Wall -Wextra -Werror `
        -Ititan_rtthread `
        tests\test_servo_feedback_poll_c.c `
        titan_rtthread\servo_feedback_poll.c `
        titan_rtthread\scs0009_transaction.c `
        titan_rtthread\scs0009_stream.c `
        titan_rtthread\scs0009_packet.c `
        -o tests\test_servo_feedback_poll_c.exe
    Assert-NativeSuccess 'Servo feedback poll C build'
    & .\tests\test_servo_feedback_poll_c.exe
    Assert-NativeSuccess 'Servo feedback poll C tests'
    & gcc -std=c99 -Wall -Wextra -Werror `
        -Ititan_rtthread `
        tests\test_servo_group_readonly_c.c `
        titan_rtthread\servo_group_readonly.c `
        titan_rtthread\scs0009_transaction.c `
        titan_rtthread\scs0009_stream.c `
        titan_rtthread\scs0009_packet.c `
        -o tests\test_servo_group_readonly_c.exe
    Assert-NativeSuccess 'Eight-servo read-only group build'
    & .\tests\test_servo_group_readonly_c.exe
    Assert-NativeSuccess 'Eight-servo read-only group tests'
    & gcc -std=c99 -Wall -Wextra -Werror `
        -Ititan_rtthread `
        tests\test_single_finger_pipeline_c.c `
        titan_rtthread\grip_policy.c `
        titan_rtthread\grip_pose_bank.c `
        titan_rtthread\servo_safety_gate.c `
        titan_rtthread\servo_motion_monitor.c `
        titan_rtthread\scs0009_packet.c `
        -o tests\test_single_finger_pipeline_c.exe
    Assert-NativeSuccess 'Single-finger pipeline C build'
    & .\tests\test_single_finger_pipeline_c.exe
    Assert-NativeSuccess 'Single-finger pipeline C tests'
    & gcc -std=c99 -Wall -Wextra -Werror `
        -Ititan_rtthread `
        tests\test_smart_hand_vision_state_c.c `
        titan_rtthread\smart_hand_vision_state.c `
        titan_rtthread\grip_policy.c `
        titan_rtthread\eight_servo_pose_bank.c `
        -o tests\test_smart_hand_vision_state_c.exe
    Assert-NativeSuccess 'Vision state C build'
    & .\tests\test_smart_hand_vision_state_c.exe
    Assert-NativeSuccess 'Vision state C tests'
    & gcc -std=c99 -Wall -Wextra -Werror `
        -Ititan_rtthread `
        tests\test_smart_hand_sequence_guard_c.c `
        titan_rtthread\smart_hand_sequence_guard.c `
        -o tests\test_smart_hand_sequence_guard_c.exe
    Assert-NativeSuccess 'Sequence guard C build'
    & .\tests\test_smart_hand_sequence_guard_c.exe
    Assert-NativeSuccess 'Sequence guard C tests'
    # smart_hand_protocol.c is linked because the test pins the encoded STATUS
    # v1 and AITRUST v1 wire bytes (including their CRC16), not just the args.
    & gcc -std=c99 -Wall -Wextra -Werror `
        -Ititan_rtthread `
        tests\test_smart_hand_status_telemetry_c.c `
        titan_rtthread\smart_hand_status_telemetry.c `
        titan_rtthread\smart_hand_protocol.c `
        -o tests\test_smart_hand_status_telemetry_c.exe
    Assert-NativeSuccess 'STATUS/AITRUST telemetry C build'
    & .\tests\test_smart_hand_status_telemetry_c.exe
    Assert-NativeSuccess 'STATUS/AITRUST telemetry C tests'
    & python -m unittest tests.test_titan_linkage_check -v
    Assert-NativeSuccess 'Titan linkage unit tests'

    Write-Host '[8/8] Titan canonical/Studio source sync'
    & (Join-Path $PSScriptRoot 'check_titan_sync.ps1') -StudioProject $StudioProject
    if (-not $?) {
        throw 'Titan source sync check failed'
    }

    Write-Host 'ALL LOCAL CHECKS PASSED'
}
finally {
    Pop-Location
}
