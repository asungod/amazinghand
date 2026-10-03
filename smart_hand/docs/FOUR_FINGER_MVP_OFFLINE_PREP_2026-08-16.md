# 四指抓握 MVP：M2×18 到货前离线准备包

**日期**：2026-08-16  
**状态**：`OFFLINE_ONLY_WHILE_M2X18_PENDING`  
**硬件访问**：`false`

> 本文件只安排软件、测试、证据和操作资料准备。它不授权上电、接线、烧录、接 6V、
> 移动舵机、装配舵盘/连杆、填写校准值或执行抓握。

## 1. 当前事实基线

已确认：

- MaixCAM2 真实 YOLO11 → Titan UART2 → ACK 闭环已稳定；
- Titan STATUS 生产路径已同步到 D 盘 Studio 工程并成功编译；
- 两颗 SCS0009 已固定在单指框架；
- 舵盘、球头拉杆和完整手指机构尚未完成；`M2×18` 未到货；
- 外部舵机 6V 未接入；校准 CSV 为空；生产姿态库未配置；
- 当前 `SERVO_GATE_COUNT=2` 仍是单指/两舵机安全门实现，不能被表述为八舵机执行层；
- “四指”在策略文档中表示最终目标（预计 8 只舵机），不是当前已验收的硬件状态。

证据来源：

- `docs/SINGLE_FINGER_MOUNTED_CALIBRATION_GATE_2026-08-15.md`
- `docs/SINGLE_FINGER_ASSEMBLY_ORDER_RECONCILIATION_2026-08-15.md`
- `GRIP_POLICY_MVP.md`
- `docs/STATUS_生产实现交接报告_2026-08-16.md`

## 2. 到货前允许完成的最小任务

### A. 构建与协议回归（可立即完成）

1. 保留当前已编译的 `Debug/rtthread.hex`、STATUS 源文件和构建日志哈希。
2. 重跑 `smart_hand/host/run_all_checks.ps1`，确认规范源与 D 盘 Studio 工程仍同步。
3. 重跑 STATUS 专项测试，确认以下边界不回退：
   - STATUS 不占用 ACK pending；
   - 旧端仍能处理 PING/VISION/ACK；
   - `GATE_PRESENT=0` 时 armed/fault 为 `UNKNOWN`；
   - 无舵机写包时 `submit` 不能为 `SUBMITTED`。
4. 只做静态审查：当前代码没有把 `INTENT`、`accepted`、`ACK` 或 `actionable=0` 当作舵机已执行。

### B. 四指软件接口前置设计（不改生产行为）

1. 只冻结**逻辑角色名**，不填写真实 ID、方向、中心、软限位或姿态值：

   ```text
   F1_PROXIMAL, F1_DISTAL,
   F2_PROXIMAL, F2_DISTAL,
   F3_PROXIMAL, F3_DISTAL,
   F4_PROXIMAL, F4_DISTAL
   ```

2. 四指配置完成的判据先写成结构规则：每个角色必须有唯一总线 ID；每个抓握意图
   必须提供完整的 8 角色目标；任何缺项、重复 ID、未校准角色均为不可执行。
3. 角色名和规则只用于离线文档/测试夹具；不得把占位角色写入
   `config/servo_calibration_template.csv`、生产姿态库或 Titan C。
4. 继续使用当前三类意图映射（39/41/65），但全部保持
   `NOT_CONFIGURED`/`actionable=0`，直到单指和整手实测数据具备。

离线结构校验已落地到：

- `host/four_finger_config_rules.py`
- `tests/test_four_finger_config_rules.py`
- `validation_reports/four_finger_bringup_session_template_2026-08-16.md`

它只检查八角色完整性、fixture ID 唯一性、显式校准标志和姿态覆盖；不会读取生产
校准 CSV，也不会授权任何总线写入。到货后的现场记录统一使用验收模板，保持 Gate 和证据层级分离。

### C. 证据与记录模板准备（不接硬件）

1. 为每个单指建立独立记录目录或会话 ID，避免把散置台架证据与装框/整手证据混在一起。
2. 到货后每次现场操作必须记录：固件哈希、Maix 版本、舵机 ID、供电电压/限流、
   机械版本、操作门、停止原因和原始日志。
3. 预先准备四类证据标签：
   - `OFFLINE`：纯软件/离线测试；
   - `LOOSE_BENCH`：散置舵机台架；
   - `MOUNTED_SINGLE_FINGER`：装框单指；
   - `FOUR_FINGER_GRASP`：四指真实抓握。
4. 任何日志、截图或演示若没有明确标签，不得用于证明四指动作。

## 3. M2×18 到货后的现场依赖（当前不执行）

顺序必须是条件门，而不是按日期强行跨门：

```text
到货清点/断电照片
  → 单指机构与指壳状态核对
  → Gate 0：装框照片审查
  → Gate 1：装框后只读复核（不动作）
  → Gate 2：按官方顺序装手指机构、拉杆和 link
  → Gate 3：电气中点下安装舵盘
  → Gate 4：单指低幅、方向、中心、软限位校准
  → 其余三指逐指重复
  → 八舵机 ID/总线/供电验证
  → 空载四指同步小步
  → 单物体一次抓握
  → 视觉触发抓握
```

解除当前暂停前，必须由现场确认：

- 到货 `M2×18` 数量是否满足每指 2 根；
- link 用 `M2 L25` 是否在手；
- 手指机构、柔性指壳、Custom servo horn、M2×10/螺母及垫圈/热塑螺钉是否齐备；
- 舵机左右位置、输出轴方向和线束是否与官方页及现场照片一致。

以上均不能由模型凭外观猜测。

## 4. 到 8 月 25 日的可行性判断

在不改变安全边界的前提下，**软件与证据准备可以在 8 月 25 日前完成**；
四指真实抓握能否完成，取决于 `M2×18` 到货时间、其余机械件齐套、逐指校准耗时和
现场是否出现发热/堵转/通信异常。当前不能承诺四指真实抓握已经排期完成。

最小成功线应按以下优先级执行：

1. 先保证 Titan/Maix/STATUS/ACK 回归可重复；
2. 再完成一指可控、可停止、可记录；
3. 再扩展到四指总线和空载同步；
4. 最后才做固定物体单次抓握与视觉触发。

若机械件或校准时间不足，交付应降级为“真实视觉 + UART/STATUS + 安全锁定展示”，
不能用 Mock 或 ACK 日志替代四指抓握证据。

## 5. 明确禁止的提前动作

- 不运行 `center_hold_scs0009_pair.py` 或 `finger_smoke_scs0009.py`；
- 不接外部 6V，不把 Titan/Maix 的 3V3/5V 当舵机供电；
- 不填写 `config/servo_calibration_template.csv` 的中心、方向或软限位；
- 不把两舵机单指夹具测试扩写成八舵机整手验收；
- 不修改生产协议、Titan C、Maix 生产代码或 D 盘 Studio 工程来“提前模拟”四指动作；
- 不把 STATUS 的 `accepted`、`actionable`、`SUBMITTED` 之外的字段写成真实执行证明。

## 6. 主模型/辅助模型分工

辅助模型可继续做：

- 文档一致性、静态代码审查、离线测试、日志/证据索引、构建同步检查；
- 四指角色/配置规则的离线测试夹具，但只能使用 `FIXTURE` 数据；
- 到货后的操作卡和停止条件草案。

只有主模型在现场授权：

- 任意上电、接线、烧录、6V、舵机动作；
- 真实 ID/方向/中心/软限位和姿态值确认；
- 单指或四指抓握验收；
- 机械件不足时的替代方案裁决。

## 7. 交接检查项

完成本离线包后，交付必须包含：

1. 修改文件完整路径；
2. 离线测试命令及结果；
3. `hardware_accessed=false`；
4. 未填写校准/姿态数据声明；
5. 到货后仍需用户现场确认的事项清单；
6. 不得外推为四指真实抓握的证据边界。
