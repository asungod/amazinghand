# supported_class_mock_probe 使用说明（2026-08-14）

配套脚本：`maixcam2/supported_class_mock_probe.py`
配套测试：`tests/test_supported_class_mock_probe.py`
规范来源：`docs/NEXT_SUPPORTED_CLASS_MOCK_TEST_PLAN_2026-08-14.md` §2.2

本说明只讲怎么用。**同一份脚本覆盖 39/41/65，换类别不需要改任何源码。**
脚本本身在三轮之间字节不变，可用 SHA-256 自证。

## 1. 需要放到 MaixVision 应用目录的文件

```text
main.py                          （生产，不改）
protocol.py                      （生产，不改）
link_monitor.py                  （生产，不改）
target_tracker.py                （生产，不改）
vision_source.py                 （生产，不改）
supported_class_mock_probe.py    （本脚本，测试用，可随时删除）
```

脚本依赖 `protocol.py` 与 `link_monitor.py`，必须与它们同目录。

## 2. 选类别：改一个纯数据文件，不改源码

在**同一目录**建立文件：

```text
supported_class_mock_probe_selection.txt
```

内容只写一行数字：

```text
39
```

换轮次时把这一行改成 `41`、再改成 `65`。这是纯数据文件，不是源码；
脚本、生产文件的哈希都不会变。

- 该文件不存在、内容为空、写了 `3` / `0` / `40` / 负数 / 小数 / 非数字 →
  脚本**拒绝运行并退出**（返回码 2），不编码任何帧、不打开串口。
- 不提供默认类别，没有"猜一个"的回退。

## 3. 干跑（默认）

在 MaixVision 打开 `supported_class_mock_probe.py`，点运行。
默认是 `dry_run`：**只打印将要发送的帧**，不打开串口、不发字节。

```json
"mode": "dry_run"
"outcome": "DRY_RUN"
"class_id": 39
"expected_titan_action": "CYLINDRICAL_GRASP"
"expected_titan_pose": "NOT_CONFIGURED"
"expected_titan_actionable": 0
"hardware_accessed": false
```

`DRY_RUN` 只表示"没做任何危险动作"，**不代表链路通过**。
在电脑上运行时永远停在干跑：电脑不会被识别为 `maixcam2`。

## 4. 真机发送：设备身份 + 三个令牌

真机发送同时需要下面两件事成立，缺一即退回干跑、零发送：

**A. 设备必须被正面识别为 MaixCAM2。**
脚本读取 `maix.sys.device_id()`，只有精确等于 `"maixcam2"` 才允许。
没有 `maix`、没有 `device_id`、调用报错、返回其他名字（含 `maixcam`、
大小写不同、带空格）→ 一律干跑，**不会配置 pinmap、不会打开 UART**。
仅仅能 `import maix` 是不够的。

**B. 选择文件里必须写全三行令牌。**

```text
39
live=ENABLE
live_ack=SERVO_DISCONNECTED_NO_5V
live_class=39
```

`live_class` 必须与第一行的类别**完全相等**。

## 5. 每轮必须重新确认 live_class（重要）

换类别时要改**两处**：类别行和 `live_class`。

| 轮次 | 类别行 | live_class | 结果 |
|---|---|---|---|
| A | `39` | `live_class=39` | 允许发送 |
| B | `41` | `live_class=39`（忘了改） | **退回干跑，零发送**，报告写 `stale authorisation` |
| B | `41` | `live_class=41` | 允许发送 |
| C | `65` | `live_class=65` | 允许发送 |

这条规则的目的：授权只对当前这一轮的这一个类别有效，不会因为上一轮写过令牌
就自动延续到下一个类别。

发送时长固定 `10` 秒，`PING` 每 1000 ms、`VISION` 每 500 ms，
对应计划 §4.4 的量级（约 10 个 PING + 20 个 VISION，共约 30 帧）。

## 6. 运行期失效即停

真机发送过程中出现下列任一情况，脚本**立即停止发送**并输出 `ABORTED`：

- `serial.read` 抛异常
- 收到畸形 ACK（参数个数不对）
- ACK 判定为 `rejected` 或 `unexpected`
- 写入失败或部分写入
- 任何一帧 ACK 超时
- `rx_errors` / `tx_fail` / `malformed` / `timeout` / `rejected` / `unexpected`
  任一计数非零

报告字段：

```json
"outcome": "ABORTED"
"abort_reason": "……具体原因……"
"hardware_accessed": true
"link_stats": "sent=… acked=… timeout=… …"
"rx_errors": 0
"error_counters": {...}
```

只有**无中止、六个错误计数全为 0、且 `sent - acked <= 1`** 时才会输出
`"outcome": "PASS"`。

返回码：`PASS` → `0`；`ABORTED` → **非 0**；选择被拒 → `2`；合法干跑 → `0`。
看到 `ABORTED` 就按计划 §7 处理，不要重跑凑数据。

## 7. 三轮之间必须做的一步

停止脚本后，**等 Titan 打印**：

```text
smart_hand: VISION_OFFLINE; cleared vision; sequence baseline reset
```

再开始下一轮。跳过这一步会让整轮 VISION 被判 `ignored_old` 而不进业务层，
且 Maix 侧 `acked` 仍会正常增长，看起来一切正常但实际什么都没测到。
详见计划 §5.2。

## 8. 测完回到 class=3

不需要"改回去"，因为全程没改过任何生产文件：

1. 停止本脚本；
2. 删除 `supported_class_mock_probe_selection.txt`（至少删掉 `live` 三行）；
3. 等 `sequence baseline reset`；
4. 运行标准 `main.py`，`vision_source.py` 未改动，mock 默认即 `class=3`；
5. Titan 应恢复 `reason=unsupported_class` / `pose=NO_ACTION` / `actionable=0`。

## 9. 电脑侧（可选，用于审查）

```powershell
cd "C:\Users\zzh\OneDrive\Desktop\PCBBOM\嵌赛物联网"
python smart_hand\maixcam2\supported_class_mock_probe.py --class 39
python -m unittest smart_hand.tests.test_supported_class_mock_probe -v
```

电脑上即使写全 `--live --live-ack … --live-class …` 也不会发送：
设备身份检查通不过，脚本会明确拒绝并说明原因。

## 10. 硬边界

- 本脚本没有任何舵机能力。
- 本脚本从不写文件；导入时不做任何事、不 import `maix`、不碰硬件。
- 类别只允许 `39` / `41` / `65`；其余五个字段固定
  `320, 240, 80, 120, 96`，没有任何开关可以改。
- 若 MaixVision 无法创建或编辑该选择文件，**不得改用编辑源码**；
  改用设备 shell 写入该文件，或停止并上报。
