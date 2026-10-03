# 三类物体抓握策略 MVP

## 目的和边界

本策略把 MaixCAM2 的稳定 `VISION` 结果转换为 Titan 未来可执行的抓握意图，先锁定
宿舍和实验室都容易准备的三类物体。它解决“识别到了什么之后做什么”，不包含舵机
角度、速度、力矩、轨迹或真实安全停止实现。

Titan 运行时已包含 `grip_policy.c` / `grip_pose_bank.c`。2026-08-14 至 2026-08-15
在无舵机 10 秒窗口内观察到 39→`CYLINDRICAL_GRASP`、41→`POWER_GRASP`、
65→`PRECISION_GRASP`，且均为 `pose=NOT_CONFIGURED` / `actionable=0`。
这不是姿态或舵机验收。主机参考实现仍位于 `host/grip_policy_model.py`。
归档：`validation_reports/supported_class_mock_2026-08-15.md`。

## 首版演示对象

类别 ID 使用 YOLO COCO 的零基索引，与当前 `vision_source.py` 示例一致。

| COCO ID | 物体 | 抓握意图 | 演示说明 |
|---:|---|---|---|
| 39 | bottle / 瓶子 | `CYLINDRICAL_GRASP` | 四指围绕瓶身形成圆柱包络 |
| 41 | cup / 杯子 | `POWER_GRASP` | 面向杯身的通用包络抓握；首版不处理杯把 |
| 65 | remote / 遥控器 | `PRECISION_GRASP` | 使用较小闭合量夹持薄长物体 |

其他类别、置信度不足或非法检测一律输出 `NO_ACTION`。首版不根据画面坐标控制机械手
空间移动；固定底座演示时由操作人员把识别到的物体放入手指可抓区域，因此不需要
机械臂。

## 输入约束

输入沿用 v0.1 `VISION` 的六个参数：

```text
(CLASS_ID, CX, CY, W, H, CONFIDENCE)
```

- 六个字段必须是整数；
- 类别和坐标/尺寸均不得超过 65535，以匹配当前 Titan 校验边界；
- `W/H` 必须大于 0；
- `CONFIDENCE` 必须为 0–100；
- MVP 的最低动作置信度为 70；
- Maix 的三帧稳定与 750ms 失效只负责视觉防抖，不能替代 Titan 本地目标新鲜度。

## 决策和安全顺序

```text
VISION 合法且目标稳定
        ↓
类别在白名单且置信度 ≥ 70？──否──> NO_ACTION
        │是
        ▼
生成抓握意图
        ↓
Titan 动作安全门检查
link online + armed + fresh target + no fault
        │
        ├─失败──> NO_ACTION / SAFE_STOP_REQUEST
        ▼
执行已校准的舵机轨迹（尚未实现）
```

抓握策略绝不能直接绕过 `ACTION_SAFETY_DESIGN.md` 的授权门。通信在线也不代表目标
仍有效；PING 继续到达而 VISION 已停止时，禁止重复执行最后一次抓握意图。

## 真机校准前保持为空的内容

每种抓握最终需要 8 个舵机的目标位置、速度和电流/负载阈值，但这些值必须按单指到
整手逐步实测，当前不得凭空填写。建议未来用独立配置表保存，而不是把位置常量散落
在通信线程中。

| 抓握意图 | 舵机目标 | 速度 | 堵转/负载阈值 | 当前状态 |
|---|---|---|---|---|
| `CYLINDRICAL_GRASP` | 待单指/整手校准 | 待测 | 待读取 SCS0009 反馈后确定 | 未实现 |
| `POWER_GRASP` | 待单指/整手校准 | 待测 | 待读取 SCS0009 反馈后确定 | 未实现 |
| `PRECISION_GRASP` | 待单指/整手校准 | 待测 | 待读取 SCS0009 反馈后确定 | 未实现 |

## 验收场景

后续实物至少验证：

1. 单独出现瓶子、杯子、遥控器时，分别得到正确抓握意图；
2. 多目标同时出现时，Maix 的目标选择保持稳定，不来回切换；
3. 未支持物体和置信度 69 时不产生动作；
4. 目标消失超过 750ms 后不再产生新的 VISION；
5. Titan 本地目标过期、链路断开或故障锁存时，即使策略匹配也不能开始动作；
6. 人工放入物体的流程中，物体未进入可抓区域时不得自动闭合。

