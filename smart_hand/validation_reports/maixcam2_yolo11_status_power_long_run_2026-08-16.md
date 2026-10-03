# MaixCAM2 真实 YOLO + Titan STATUS 长稳记录（2026-08-16）

## 证据边界

本记录根据用户现场运行日志整理。它证明真实 MaixCAM2 YOLO、UART2、Titan 策略与 STATUS 回显在无舵机条件下长时间协同运行；不证明舵机动作、机械校准或四指抓握。

- 舵机 6V：未接
- 舵机总线：未接
- 校准 CSV：未配置
- 生产姿态库：未配置
- `submit=SUBMITTED`：未出现
- `gate=ARMED`：未出现

## 现场日志摘要

代表性 ACK 序号从 `288` 持续到 `1174`，均为 `status=0 result=acked`。

长稳统计末段：

```text
sent=1169
acked=1168
rejected=0
unexpected=0
malformed=0
timeout=1
consecutive_timeout=0
pending=0
rtt_avg_ms=27.0
rtt_max_ms=145.0
```

视觉末段：

```text
mode=yolo11
frames=7140
detections=12809
selected=4999
no_target=2141
acquired=3
updated=4988
switches=0
lost=2
active=1
read_errors=0
```

## STATUS 语义证据

主要状态反复出现：

```text
AUTH link=ON vis=ON stale=0 act=POWER reason=accepted pose=NOT_CONFIGURED submit=NOT_CONFIGURED gate=UNKNOWN
```

这表示视觉目标被 Titan 策略接受，但姿态未配置，因此没有动作提交。`POWER` 是策略结果，不是舵机执行结果。

日志还出现低置信度安全路径：

```text
AUTH link=ON vis=ON stale=0 act=NONE reason=low_confidence pose=NO_ACTION submit=UNKNOWN gate=UNKNOWN
```

## 结论

本轮可采信为：

1. 真实 YOLO 检测与目标跟踪正常运行；
2. Maix↔Titan UART2 ACK 长稳运行，只有一次瞬时超时，随后恢复；
3. Titan STATUS 正确区分 `accepted + NOT_CONFIGURED` 与 `low_confidence + NO_ACTION`；
4. 无舵机写包、无机械动作、无真实抓握。

本记录不得用于证明：

- 舵机执行；
- 中心/方向/软限位校准；
- 单指或四指抓握；
- 真实物体受力或姿态保持。

