# OpenSignHand 软件侧冻结记录（2026-09-18）

## 结论

OpenSignHand 的三类基础手型软件闭环已完成主机侧冻结，范围限定为 `OPEN_PALM`、`FIST`、`V_SIGN`。本记录不等同于 MaixCAM2 真机识别验收，也不证明任何机械手动作已经通过。

## 本次冻结内容

- 独立手语训练状态机，不覆盖既有康复状态机；
- MaixCAM2 21 点地标几何特征和三类规则分类器；
- 人工选择、人工确认开始、取消、超时、故障和终态 CSV；
- 同源网页控制接口与只读状态接口；
- POST 分片完整性检查；
- 网页训练意图 2 秒 TTL，过期后拒绝执行；
- 终态日志失败重试和同一会话幂等写入；
- Maix 主循环 tick 贯通视觉分类器，避免混用时钟；
- 独立匿名地标采集脚本，默认不同意且不访问 UART/Titan/舵机；
- 部署标记 `opensignhand.enable`：只有专用部署目录启用手语模式和网页，原康复项目保持默认关闭。

## 自动化验证

在项目根目录执行：

```powershell
python -m py_compile smart_hand/maixcam2/web_stream.py smart_hand/maixcam2/live_sidecar.py smart_hand/maixcam2/sign_lesson.py smart_hand/maixcam2/sign_session_log.py smart_hand/maixcam2/rehab_hand_source.py smart_hand/maixcam2/main.py smart_hand/maixcam2/sign_landmark_capture.py
python -m unittest smart_hand.tests.test_sign_core smart_hand.tests.test_sign_dataset_tools smart_hand.tests.test_sign_landmark_capture smart_hand.tests.test_sign_integration smart_hand.tests.test_web_stream smart_hand.tests.test_live_sidecar smart_hand.tests.test_maix_main -q
```

结果：`Ran 93 tests ... OK`。

覆盖范围包括：三类/未知手型逻辑、状态机拒绝式默认值、重复故障日志幂等、日志失败重试、匿名采集格式、同源接口、请求体分片、指令 TTL、只读遥测及既有 Maix 主循环回归。

## 真实边界

- 当前课程是基础手型原型，不映射完整中国手语词义；
- 三个课程全部为 `screen_only`，`mechanical_pose` 为空；
- 未点击人工确认时不会开始课程；
- 网页不能提交舵机角度，也不能绕过状态机；
- Titan NPU 未部署手语或音频神经网络；
- NationalCSL-DP 未下载、未用于当前 MVP 指标；
- 当前尚无不少于 3 人、每类 10 次的真实采集数据，因此不发布宏 F1、误接受率或跨人泛化结论；
- 真机验收、PPT 实拍和演示视频仍需在硬件现场完成。

## 真机前必须完成

1. 将专用部署目录整体导入 MaixVision，确认 `opensignhand.enable` 同级存在；
2. 舵机电源保持断开，先验证三课程选择、开始、取消、超时、日志和网页；
3. 分至少两名匿名参与者采集地标，计划目标为 3 人 × 3 类 × 10 次，并额外采集 `UNKNOWN`；
4. 使用 `sign_landmark_dataset.py` 校验，再运行 `evaluate_sign_classifier.py`；
5. 如需启用任何机械辅助示范，必须另做姿态、连杆、供电和 Titan gate 真机验收，不得仅修改课程配置绕过。
