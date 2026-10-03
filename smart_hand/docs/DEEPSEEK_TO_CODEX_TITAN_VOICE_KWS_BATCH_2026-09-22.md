# DeepSeek → Codex 交接报告：Titan 端侧语音 KWS 第一批

任务书：`outputs/OpenSignHand_Hardware_Bringup_2026-09-21/DEEPSEEK_TITAN_EDGE_SPEECH_TASK_2026-09-22.md`
日期：2026-09-22　范围：阶段 A（采集）代码 + 阶段 B（训练/量化）管线 + 阶段 C（端侧推理）引擎 + 主机验证

---

## 1. 交付物

**新增源码**

| 文件 | 作用 |
|---|---|
| `smart_hand/titan_rtthread/voice_config.h` | 契约常量单一来源，被 Python 镜像解析校验 |
| `smart_hand/titan_rtthread/voice_features.h/.c` | float32 log-Mel 前端，零依赖、可主机测试 |
| `smart_hand/titan_rtthread/voice_audio.h/.c` | 无锁 SPSC PCM 环形缓冲，可主机测试 |
| `smart_hand/titan_rtthread/voice_audio_titan.h/.c` | FSP PDM 绑定 + 真机探测（需设备工具链） |
| `smart_hand/titan_rtthread/voice_kws.h/.c` | int8 推理引擎（conv2d / dwconv / avgpool / fc） |
| `smart_hand/titan_ai/voice/voice_features_ref.py` | 前端 Python 镜像（训练必须用它） |
| `smart_hand/titan_ai/voice/voice_quant.py` | TFLite requantisation 算术的 Python 移植 |
| `smart_hand/titan_ai/voice/train_voice_kws.py` | 训练 → int8 TFLite → C 导出 |
| `smart_hand/tests/test_voice_{features,audio,kws}_{c.c,.py}` | 三组主机测试 |
| `tools/voice_dataset/{README.md,record_keyword.py}` | 语料规范与采集工具 |

**新增文档**

- `smart_hand/docs/TITAN_VOICE_RECON_2026-09-22.md` —— 侦察报告 + 任务书 §3.1 三方案裁决
- `smart_hand/docs/TITAN_VOICE_MODEL_REPRODUCE.md` —— 复现流程

**未改动**任何既有文件。舵机、协议、状态机、安全门、`titan_trust` 全部原样。

---

## 2. 已验证（可复核）

| 项 | 结果 | 命令 |
|---|---|---|
| log-Mel 前端 C↔Python | **int8 输出逐位一致**；float 最大差 1.14e-05，比一个量化步长小 5461 倍 | `python -m unittest smart_hand.tests.test_voice_features` |
| PCM 环形缓冲 | 12 万采样点跨边界顺序完整；溢出语义正确 | `python -m unittest smart_hand.tests.test_voice_audio` |
| **推理引擎 vs TFLite 参考** | **分类判断 24/24 一致；logits 95.83% 逐位相同，max\|diff\|=1** | `D:\voice_kws_env\Scripts\python.exe -m unittest smart_hand.tests.test_voice_kws` |
| 训练/量化/导出 | 收敛并产出 25,360 B int8 TFLite + C 头/源 | `train_voice_kws.py --synthetic --epochs 15` |
| 设备工具链可编译 | 5 个源文件用工程真实旗标 `-fsyntax-only` 全部 exit=0 零警告 | 见 §5 |

---

## 3. 未验证（**请勿据此宣称完成**）

1. **真实识别准确率不存在。** 仓库零音频资产，全部结果出自合成语料自检，`voice_training_metrics.json` 的 `field_accuracy_validated` / `hardware_inference_validated` 恒为 false。
2. **真机采样率未实测。** 配置值 16000 Hz 有重大疑点：`SINCRNG=5/SINCDEC=124/CKDIV=0` 与芯片复位默认值一字不差，且 PDM 时钟源在全仓库无任何配置。**若真实采样率非 16000 Hz，前面所有离线结果需按实测值重训。**
3. **未在真机编译/烧写/运行过。** 只做了 `-fsyntax-only`，没有链接，没有上电。
4. `voice_audio_titan.c` 中回调→缓冲位置的映射假设驱动会在缓冲末尾回绕，**该行为未在 FSP 头文件中写明**，代码内已标注，需 `probe()` 实测确认。
5. 未跑 30 分钟无溢出、未测真机推理耗时与 RAM 水位。当前编译为 `-O0`（`Debug/src/subdir.mk` 硬编码），推理耗时有风险。

---

## 4. 需要你裁决的三件事

1. **语音只读状态如何上报？** 固件 `RT_CONSOLE_DEVICE_NAME="null"` 且 FINSH 未开，**没有任何调试终端**，`rt_kprintf` 输出会被丢弃。任务书 §4-D"先通过调试终端验证"此路不通。要么扩展 UART2 协议（新增独立带版本号与 CRC 的消息），要么语音状态在真机上不可见。
2. **是否接受改 `board.h:20 RA_SRAM_SIZE`？** RT-Thread 堆被它硬卡在 386,060 B，任务书 §5 的"512 KB 工作区"目标超出 138,228 B。本次实现改走**静态数组**绕过（有厂商 NPU 例程先例），未动该常量。
3. **首轮真机验证前是否先统一固件版本？** V_SIGN 文档记录的 `F12600ADE0…` 与现存两个 hex 都不匹配，且源码 mtime 晚于文档——"已刷写"这句话当前无法复核。

---

## 5. 审查要点（10 行内）

1. `voice_features.c` 与 `voice_features_ref.py` 是否真的逐步同构——只看 `test_voice_features.py` 的 int8 逐位一致断言是否保留。
2. `voice_kws.c` 的三个算子里 `(x - in_zero_point)` 是否都在——漏掉这一项会让结果全错，且**只有** `test_voice_kws.py` 能发现。
3. `test_voice_kws.py` 是否仍传 `experimental_preserve_all_tensors=True`。**去掉它测试会"通过但毫无意义"**（读的是被复用的中间缓冲），这是本次开发踩过的坑。
4. `_validate_topology()` 是否仍在导出时拒绝偏离既定拓扑的模型——C 引擎只实现那一种结构。
5. `voice_avgpool2x2_valid` 不做 rescale，依赖池化层出入 scale 与 zero point 相等；`test_engine_relies_on_matching_pool_scales` 是否仍在守这条。
6. `pdm_callback` 是否只搬数据和计数，没有任何日志/特征/推理——ISR 纪律。
7. `voice_audio_titan.c` 里"回绕假设"的注释是否还在，别把未验证假设读成已验证。
8. `voice_config.h` 是否仍是常量唯一来源（`test_header_constants_match_python_reference` 在守）。
9. 度量文件里三个 `false` 标志是否仍是 `false`（`test_metrics_never_claim_field_validation` 在守）。
10. 是否新增了任何**未标注为待补**的准确率数字——任务书 §8 明令禁止。

---

## 6. 复现命令

```powershell
cd <项目根>
python -m unittest smart_hand.tests.test_voice_features smart_hand.tests.test_voice_audio -v
D:\voice_kws_env\Scripts\python.exe -m unittest smart_hand.tests.test_voice_kws -v
python -m py_compile smart_hand/titan_ai/voice/train_voice_kws.py
```
