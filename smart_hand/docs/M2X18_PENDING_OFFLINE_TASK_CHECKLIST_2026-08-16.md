# M2×18 到货前离线任务清单（2026-08-16）

状态：`OFFLINE_ONLY` · `hardware_accessed=false`

这张清单是 `FOUR_FINGER_MVP_OFFLINE_PREP_2026-08-16.md` 的执行版。完成它不会解除任何
硬件安全门，也不会授权上电、接线、烧录、6V 或舵机动作。

## 2026-08-16 本批完成记录

- 四指 8-role fixture 规则已补齐 fail-closed 检查：8 个非空且唯一的 fixture ID、合法
  ID 范围、精确三种姿态集合、每种姿态完整覆盖 8 个角色、全角色显式 calibrated。
- `tests/test_four_finger_config_rules.py`：12/12 通过。
- `tests/test_protocol_status_proposal.py`：15/15 通过。
- `host/run_all_checks.ps1` 已纳入四指规则、八舵机规划和整组停机模型及其测试的语法检查；
  全量离线检查输出 `ALL LOCAL CHECKS PASSED`，Python discover 当前收集 326 项测试。
- 当前只读记录的 Studio 构建产物：`D:\Micu\RTTWorkspace\titan_uart_test\Debug\rtthread.hex`，
  长度 340522 bytes，时间戳 `2026-08-16 10:42:17 +08:00`，SHA-256
  `F9E0192F9B54546FABA5B4B7C06F4E767E0CC3977D9204305C6BF4765C847D40`。该哈希只标识当前文件，
  不单独证明已烧录或正在运行。
- 已新增 `TITAN_EIGHT_SERVO_SAFETY_EXPANSION_STATIC_AUDIT_2026-08-16.md`，明确当前
  Titan 仍是 2 舵机安全链，以及扩到 8 舵机前必须满足的全组反馈、原子计划、总线写入、
  torque-off、motion monitor、STATUS 和时间预算门槛。
- 已新增 `M2X18_ARRIVAL_AND_GATE_EVIDENCE_TEMPLATE_2026-08-16.md`，用于到货后按 Gate
  留存事实证据；模板不包含真实 ID、方向、中心、软限位或姿态值。
- 已新增 `host/eight_servo_plan_model.py` 与 `tests/test_eight_servo_plan_model.py`：
  8/8 角色、ID、目标和新鲜反馈必须完整，否则整组无效。
- 已新增 `host/eight_servo_group_stop_model.py` 与
  `tests/test_eight_servo_group_stop_model.py`：逐一尝试 8 个 ID，任一失败仍继续，
  失败/中断保持 fault 并要求外部 6V 断开；该模型不生成舵机包。

本批未访问硬件，未修改生产 C、协议、校准 CSV、生产姿态库或 D 盘 Studio 工程。

## A. 每日软件回归（可直接执行）

- [ ] 在仓库根目录运行：

  ```powershell
  pwsh -File smart_hand\host\run_all_checks.ps1
  ```

  完成判据：输出 `ALL LOCAL CHECKS PASSED`，且最后一步的规范源/Studio 哈希全部 `True`。

- [ ] 运行 STATUS 专项测试：

  ```powershell
  python -m unittest smart_hand.tests.test_protocol_status_proposal -v
  ```

  完成判据：所有测试为 `ok`；不得出现 ACK 统计被 STATUS 占用、旧端兼容失败或
  `GATE_PRESENT=0` 仍报告 armed/fault 的回归。

- [ ] 保存本次测试输出、`Debug\rtthread.hex` 的 SHA-256 和时间戳。

## B. 四指配置前置（只做规则，不填实测值）

- [ ] 保持 `config\servo_calibration_template.csv` 只有表头；禁止写入中心、方向、软限位、
  速度或负载阈值。
- [ ] 使用逻辑角色名记录未来配置草案：
  `F1_PROXIMAL/F1_DISTAL`、`F2_PROXIMAL/F2_DISTAL`、
  `F3_PROXIMAL/F3_DISTAL`、`F4_PROXIMAL/F4_DISTAL`。
- [ ] 不分配真实舵机 ID。ID 必须在到货后逐指读回并由主模型现场确认。
- [ ] 不配置三类生产姿态。`CYLINDRICAL_GRASP`、`POWER_GRASP`、`PRECISION_GRASP`
  继续保持 `NOT_CONFIGURED` / `actionable=0`。
- [ ] 对任意离线夹具检查：8 个逻辑角色必须唯一、每个姿态必须覆盖 8 个角色；缺项、
  重复 ID、未校准角色全部判为不可执行。

## C. 证据包整理（不接硬件）

- [ ] 为现有记录标注证据层级：`OFFLINE`、`LOOSE_BENCH`、`MOUNTED_SINGLE_FINGER`、
  `FOUR_FINGER_GRASP`。
- [ ] 将 ACK、`accepted`、Maix `INTENT`、`MOTION LOCKED` 明确标为通信/意图/安全状态证据，
  不得标为舵机执行证据。
- [ ] 将两舵机散置台架报告与装框报告分开存放；不得合并成整手验收。
- [ ] 预留到货后记录字段：固件哈希、舵机 ID、供电电压、限流、机械版本、Gate 编号、停止原因。

## D. 到货前装配资料核对（只读资料）

- [ ] 阅读并保持官方顺序：机构/拉杆/link 先完成，电气中点后安装 Custom servo horn。
- [ ] 将以下项目列为 `待现场核对`，不要凭照片或记忆判定已具备：
  `M2×18` 数量（每指 2 根）、`M2 L25`、手指机构、柔性指壳、Custom horn、
  `M2×10`/螺母、垫圈和热塑螺钉。
- [ ] 保持当前单指 Gate 状态为 `PAUSED_WAITING_M2X18`。
- [ ] 到货前禁止运行：
  `center_hold_scs0009_pair.py`、`finger_smoke_scs0009.py`。

## E. 交付记录

每次完成本清单后，交接中必须写明：

1. 修改/新增文件完整路径；
2. 实际命令和测试结果；
3. `hardware_accessed=false`；
4. 校准 CSV 和生产姿态库仍为空/未配置；
5. 未完成的现场依赖和禁止外推项。

## F. 到货后才开放的门

只有在现场清点并由主模型确认后，才可依次进入：

```text
断电照片审查 → Gate 0/1 → 机构装配 → 舵盘安装 → 单指校准
→ 其余三指逐指校准 → 八舵机总线 → 空载同步 → 单物体抓握
```

任何一步出现发热、焦味、堵转、通信丢失或电流异常，立即断开外部 6V，回退到文档审查；
不得用软件 ACK 或离线测试替代现场门。
