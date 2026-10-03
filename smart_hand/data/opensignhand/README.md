# OpenSignHand 离线地标数据

本目录只保存数据格式说明和来源清单，不打包人物视频、原始照片、姓名、手机号或账号。正式训练/评估数据应放在本地受控目录，并通过 `host/sign_landmark_dataset.py` 校验后再使用。

## JSONL 格式

每行一个 JSON 对象，固定必填字段如下：

| 字段 | 要求 |
|---|---|
| `schema` | `opensignhand.landmark.v1` |
| `participant_id` | 匿名代号，例如 `P01`；不得填写姓名、手机号、邮箱 |
| `session_id` | 匿名会话代号，例如 `S01` |
| `gesture_id` | `OPEN_PALM`、`FIST`、`V_SIGN` 或 `UNKNOWN` |
| `timestamp_ms` | 非负整数，采样时间戳 |
| `landmarks` | 21 个 `[x,y]` 点，或 63 个 `[x,y,z]` 数值 |
| `source` | 样本来源说明 |
| `license` | 数据/派生数据许可证说明 |
| `consent` | 真实采集必须是 JSON 布尔值 `true`；自由文本不视为有效同意记录 |

这些标签是 OpenSignHand 的三类基础手型原型，不映射“你好”“谢谢”等正式手语词义，也不代表完整中国手语系统。`UNKNOWN` 用于未知或不应接受的动作。

示例（仅为格式示意，不能作为准确率数据）：

```json
{"schema":"opensignhand.landmark.v1","participant_id":"P01","session_id":"S01","gesture_id":"OPEN_PALM","timestamp_ms":1000,"landmarks":[[0,0],[1,0],[2,0],[3,0],[4,0],[5,0],[6,0],[7,0],[8,0],[9,0],[10,0],[11,0],[12,0],[13,0],[14,0],[15,0],[16,0],[17,0],[18,0],[19,0],[20,0]],"source":"local_demo_capture","license":"internal-research-only; no redistribution","consent":true}
```

## 离线命令

以下命令只读写 JSONL，不访问摄像头或网络：

```powershell
python smart_hand\host\sign_landmark_dataset.py validate path\samples.jsonl
python smart_hand\host\sign_landmark_dataset.py summary path\samples.jsonl
python smart_hand\host\sign_landmark_dataset.py append path\samples.jsonl --sample-file path\one_sample.json
python smart_hand\host\evaluate_sign_classifier.py path\samples.jsonl --pretty
```

`validate` 发现错误时返回非零退出码；`summary` 和评估器在无有效样本时明确失败，不生成假指标。评估器按 `participant_id` 整体留一人验证，至少需要两名不同参与者；同一人的样本不会同时进入同一折的训练上下文和测试集。当前规则分类器不拟合参数，但保留该分组边界以防后续模型发生人员泄漏。

评估输出包含四类混淆矩阵（行是实际类别，列是预测类别）、每类 precision/recall/F1、四类宏平均 F1、样本量、参与者折信息及 `UNKNOWN` false-accept rate。该 rate 定义为“实际为 `UNKNOWN` 却被预测为已知类别”的比例。若数据中没有真实 `UNKNOWN` 样本，后者为 `null`，而不是伪造 0。

## MaixCAM2 真机采集

采集脚本是独立的 [`../../maixcam2/sign_landmark_capture.py`](../../maixcam2/sign_landmark_capture.py)，不会启动项目 `main.py`，也不会打开通信端口、访问 Titan 或驱动舵机。它使用板上现有的 `/root/models/hand_landmarks.mud`，只把 21 点地标写入 `/root/opensignhand_landmarks.jsonl`；不保存照片、视频、姓名、电话或其他直接身份信息。

在 MaixVision 中以 Run File 运行前，只编辑脚本顶部的配置常量：

```python
PARTICIPANT_ID = "P01"       # 匿名代号，不要填姓名/电话
SESSION_ID = "S01"           # 匿名会话代号
GESTURE_ID = "OPEN_PALM"     # OPEN_PALM/FIST/V_SIGN/UNKNOWN
CONSENT = True                # 只有明确同意后才改为布尔 True
LICENSE = "internal-research-only; no redistribution"
TARGET_SAMPLES = 30
CAPTURE_INTERVAL_MS = 500
COUNTDOWN_SECONDS = 3
```

`CONSENT` 必须是 Python 布尔值 `True`；缺省的 `False` 或字符串 `"true"` 都会在加载摄像头前拒绝运行。脚本会先倒计时，采集期间每个固定间隔最多追加一条 JSONL 记录，达到 `TARGET_SAMPLES` 后自动停止。可用 MaixVision 的 Stop/退出操作取消；若设备触摸屏可用，也可按住并释放预览右下角的 `CANCEL` 按钮。取消不会触碰任何执行机构。

采集完成后，将 JSONL 从设备复制到受控主机目录，再运行：

```powershell
python smart_hand\host\sign_landmark_dataset.py validate path\opensignhand_landmarks.jsonl
python smart_hand\host\sign_landmark_dataset.py summary path\opensignhand_landmarks.jsonl
```

只有校验通过的派生地标数据才进入训练或评估；`UNKNOWN` 是一个允许的手型标签，用于未知/不应接受的动作，不是正式手语词义。

`Apache-2.0` 用于项目源码，不自动适用于参与者产生的地标数据。缺少单独、
可审计的公开授权时，采集器默认把数据标记为
`internal-research-only; no redistribution`。若后续决定公开数据，应先保存受控的
同意版本、日期、用途范围和撤回记录，再为数据选择明确的数据许可；公开仓库中
仍不得保存姓名、电话或匿名代号与真实身份的对应表。

## 可选轻量分类器训练

项目默认仍使用 MaixCAM2 上可解释的规则分类器。若已经采集到至少两名
不同参与者、且三类基础手型均有有效样本，可以在主机端训练一个不依赖
第三方库的标准化质心模型：

```powershell
python smart_hand\host\train_sign_classifier.py `
  path\opensignhand_landmarks.jsonl `
  path\opensignhand_gesture_model.json `
  --report path\opensignhand_gesture_report.json
```

训练脚本会复用本目录的数据校验，拒绝空数据、单一参与者、缺少类别、
维度不一致和 NaN/Inf。评估采用按 `participant_id` 留一人的完整隔离折，
输出样本量、参与者、每类计数、混淆矩阵、宏 F1 和 `UNKNOWN` 误接受率；
无法形成有效折时不生成模型。相同输入的模型 JSON 参数是确定性的。

将经过审查的模型复制为 MaixCAM2 上的：

```text
/root/models/opensignhand_gesture_model.json
```

设备端只用 Python 标准库读取固定 schema/version、18 维
`gesture_features.feature_vector`、标准化参数、质心和拒识阈值。模型缺失、
损坏、维度/schema 不匹配或参数非有限时，会自动回退到原有规则分类器，
不会阻断设备启动，也不会绕过手部存在、链路在线、视觉新鲜度和稳定保持
时间等安全前置条件。`UNKNOWN` 仅用于拒识评估，不代表正式手语词义。

## 数据来源与合规

NationalCSL-DP 来源及许可证记录在 [`manifest.example.csv`](manifest.example.csv)。本仓库不重新分发其人物视频。下载或使用原始数据前，应阅读官方发布页的研究用途、访问协议和许可证要求，并仅保存获得授权的派生地标数据。`consent` 字段是本项目本地采集记录的明确审计字段，不替代上游数据集的许可条款。
