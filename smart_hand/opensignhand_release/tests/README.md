# 测试与证据要求

## 1. 离线测试

在项目根目录运行：

```powershell
python smart_hand\host\check_maix_deploy.py --expected-mode yolo11
python smart_hand\host\run_offline_rehearsal.py --output smart_hand\outputs\offline_rehearsal_latest.json
python -m unittest smart_hand.tests.test_generate_rehab_session_report -v
```

如需验证 TitanTrust 原型，可运行其已有 Python/C 测试；但这些测试只能证明合成输入、边界输入和状态逻辑，不能证明现场精度或 Titan 固件已经烧录：

- `smart_hand/tests/test_titan_trust_training.py`；
- `smart_hand/tests/test_titan_trust_model.c`；
- `smart_hand/tests/test_titan_trust_runtime.c`。

## 2. 当前离线验收的含义

离线演练必须明确：

- `hardware_accessed=false`；
- 链路丢失时进入 `safe_stop_required`/`FAULT`；
- 校准模板不会授权物理动作；
- 没有串口、摄像头或舵机副作用。

任何离线 PASS 都不能替代真机录像和原始日志。

## 3. 真机验收矩阵

| 用例 | 证据 | 通过条件 |
|---|---|---|
| 三种课程正常训练 | 画面+CSV+日志 | 课程状态、保持、计数一致 |
| 无目标 | 画面+Titan状态 | 不产生机械动作 |
| 视觉过期/低置信度 | Titan日志 | 拒绝或安全保持 |
| UART断联/CRC错误/旧序号 | UART日志 | 超时/故障收敛，恢复需重新授权 |
| 舵机故障或机械干涉 | 现场记录 | 立即断电，不能继续凑数据 |
| 重启恢复 | 重启前后日志 | 不自动续作，不复活旧意图 |

## 4. 开源发布前检查

1. 构建干净的发布环境并记录版本；
2. 检查所有随包文件的许可证、第三方来源、模型/数据哈希；
3. 搜索并删除个人手机号、邮箱、IP、设备密钥、绝对路径和临时目录；
4. 确认没有打包 `smart_hand/third_party/STServo_Python.zip` 或未知权重；
5. 复核 README、NOTICE、UPSTREAM、DATA_AND_MODEL_SOURCES 彼此一致；
6. 重新运行离线测试，并把实际真机证据放到单独的受控附件中。

## 5. 仍未完成的证据

本目录创建时不能把下列项目写成已完成：

- NationalCSL-DP 实际使用类别、划分、下载文件哈希和预处理记录（公开来源页面已在数据清单中列出）；
- 手语/手型模型的完整来源与再分发许可；
- Titan NPU 上的手语或音频网络部署；
- 真实用户泛化、临床效果或完整手语识别；
- 未在相应报告中明确的机械动作、抓握成功率或长期耐久性。
