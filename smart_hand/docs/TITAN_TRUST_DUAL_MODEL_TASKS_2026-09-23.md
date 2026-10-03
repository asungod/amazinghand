# TitanTrust 展示闭环：DeepSeek / Gemini 分工

目标：在现有 MaixCAM2 手型识别之外，展示 Titan Mini 上**已经存在**的 TitanTrust-Tiny 三分类推理。它只评价视觉与链路输入是否可信，不识别手语、不控制舵机，也不能替代安全门控。先做可观察的真机闭环，再决定是否采集真实样本重训；本轮不继续折腾 PDM 语音。

## 两边共用的接口（先冻结）

Titan → MaixCAM2 新增只读 UART 帧：`AITRUST`，4 个 uint32 参数，依次为 `version=1, ready, class_id, vision_age_ms`。`class_id`：0=可信、1=存疑、2=异常。`ready=0` 时类别无意义，页面必须显示「未就绪」。继续沿用现有 `$TYPE,SEQ,ARGS*CRC16\r\n`、16 位序号和 128 字节上限。最多每 500 ms 一帧；不用 ACK，不参与请求重试。不改变现有 `STATUS` v1、`SIGNSTAT`、`TRAINSTAT` 的字段、频率或意义。

**2026-09-23 协议裁决：采用 A。** Titan 在 `ready=0` 时保留模型原始 `class_id`（仍限 0/1/2），接收方必须先判 `ready`；即使收到 `ready=0, class_id=0`，也只能显示「未就绪」，不能显示可信或绿色。不要改发伪造的异常类别，也不要单方面新增第四类。Gemini 的测试必须用这组反例同时验证解析快照、页面文字和颜色；`ready=1` 且帧未过期时才允许按类别显示。

网页收到帧后保存本机接收时间；超过 1500 ms 没有新帧显示「未上报／已过期」，不能继续亮绿灯。Titan 链路离线时优先显示离线。`vision_age_ms` 仅是 Titan 看到的最近视觉数据年龄，不是端到端延迟或精度。不要显示概率、准确率或「安全保证」——当前模型训练数据是合成故障注入，尚无真实场景准确率。

## 发给 DeepSeek 的任务

你只负责 Titan 端，文件所有权限定 `smart_hand/titan_rtthread/` 和对应的 Titan C 测试，不修改 `smart_hand/maixcam2/`、网页、PDM/语音、舵机控制、板级内存配置。先读现有 `titan_trust_model.*`、`titan_trust_runtime.*`、`smart_hand_uart.c`、`smart_hand_protocol.*`、`smart_hand_status_telemetry.*` 及相关测试。现有 `update_titan_trust()` 只写 `rt_kprintf`，而设备 console 为 null，所以要把**已有推理结果**按上面冻结的 `AITRUST` 帧只读上报。

要求：

1. `ready=0` 和无有效视觉帧的情况按真实状态发，不把默认 `ANOMALOUS` 冒充已验证异常；`vision_age_ms` 要有明确的缺省与饱和策略，写进交付说明。
2. 发送周期不快于 500 ms；串口写失败只计数或记录，不能阻塞既有 ACK/STATUS/机械手链路。旧协议字节及安全门控保持不变。不要把 TitanTrust 分类接入动作授权或自动开始逻辑。
3. 写最小宿主测试：帧参数、CRC、周期、无视觉、视觉过期、发送失败、原有 STATUS v1 不变。复用现有测试习惯，不为此重构驱动。
4. 做真构建并核对新产物时间与 SHA-256；**不要烧写**。若真实工程与仓库镜像有差异，列清楚，不能默默覆盖。
5. 交付简短报告：改动文件、测试/构建命令与结果、固件哈希、未验证项。合成训练指标只可称「自检」，不可称真实识别准确率。

## 发给 Gemini 的任务

你只负责 MaixCAM2 协议接收和学习者网页，文件所有权限定 `smart_hand/maixcam2/`、对应 Python 测试及部署镜像同步；不修改 Titan C、语音、舵机控制。先读 `protocol.py`、`main.py`、`web_stream.py`、`live_sidecar.py` 与现有网页/集成测试。按上面的固定 `AITRUST` 帧做接收、校验、快照、网页中文展示。

要求：

1. 四字段严格校验（版本、ready、class_id、age），错误帧忽略；`AITRUST` 是遥测，不可关闭任何 ACK pending，也不能触发训练开始或机械动作。
2. 页面增加紧凑的「Titan 端侧 AI／输入可信度参考」状态：未上报、未就绪、可信、存疑、异常、已过期、链路离线。说明它是**辅助判断**，非安全认证；不能把 MaixCAM2 手势置信度写成 Titan 的输出。颜色在 ready=0/过期/离线时不能是绿色。
3. 保持单视频流、串行轮询、同源、`textContent`、人工确认、旧康复入口和现有 API 兼容。只读展示，不添加 servo/angle 参数，不因 UI 状态自动发 POST。
4. 测试覆盖合法/非法帧、过期回退、离线优先级、旧 ACK/STATUS 不受影响。同步部署镜像并核对哈希；不假设新 Titan 固件已经烧写。交付简短报告和一张桌面端截图。

## Codex 负责审核与实物验收

我先对两份交付做协议逐字段、测试有效性和安全边界审查；只在两边一致且构建通过后决定烧写与部署。当前 Titan 上电、舵机驱动板断电。先在驱动板保持断电时核对 UART 旧链路与新 `AITRUST`，再做 10 分钟持续运行和断线/过期回退；涉及机械手动作的验收单独进行，不把遥测成功说成机械手成功。未刷写/未真机验证的环节一律标为未验证。
