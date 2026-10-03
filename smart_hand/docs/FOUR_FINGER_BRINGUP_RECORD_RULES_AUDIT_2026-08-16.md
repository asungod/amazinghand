# 四指到货后 Bring-up 记录规则离线审计

**日期**：2026-08-16  
**状态**：OFFLINE_AUDIT_ONLY / NOT_AN_OPERATION_AUTHORIZATION  
**硬件访问**：false

> 本文件只审计“到货后怎样留下可复核、可机器拒绝缺项的记录”。它不授权上电、接线、烧录、舵机枚举、扭矩使能、动作、校准或抓握；不包含真实舵机 ID、方向、中心、软限位、全手电流限值或生产姿态。

## 1. 审计边界与结论

审计对象限于四类现场记录：逐指校准、八舵机 ID/角色/总线枚举、舵机外部供电与限流、异常停机与复位前审查。

结论：仓库已经有清晰的人工 Gate、单指安全字段、八逻辑角色结构规则和两舵机反馈日志校验器，但还没有一份覆盖上述四类记录的统一机器可检查格式。当前最大的证据风险不是“没有表格”，而是 Markdown 中的 PENDING、空白、人工描述、正常结束与紧急断电混在一起，无法自动证明：8/8 枚举完整、每个校准值有来源、全手限流经过批准、异常后外部 6V 已真正关闭。

最小建议是后续新增一个只用于验收证据的 JSON 旁车记录，继续保留现有 Markdown 作为人工操作页。JSON 不读取、不生成生产校准 CSV，也不向总线发送数据；在全部规则通过前，派生结果必须是 eligible_for_next_gate=false。

## 2. 已确认事实（CONFIRMED）

### 2.1 当前四指结构规则

- host/four_finger_config_rules.py 冻结了 8 个逻辑角色：F1_PROXIMAL/F1_DISTAL 至 F4_PROXIMAL/F4_DISTAL。
- fixture 结构必须正好 8 行，ID 非空、两两唯一且为 1..253 的整数；8 个角色都必须显式 calibrated=true。
- 三种姿态必须恰好是 CYLINDRICAL_GRASP、POWER_GRASP、PRECISION_GRASP，且每种覆盖 8 个角色。
- 这些规则明确是离线 fixture 规则，不会打开串口、分配硬件 ID 或授权动作。

### 2.2 当前校准数据边界

- config/servo_calibration_template.csv 只有表头，没有数据行。
- 表头已经包含角色、ID、总线、波特率、方向、中心、软限位、最大单步、速度上限、单位状态、驱动版本、验证人、验证时间和备注。
- servo_safety_gate.c 对当前两舵机 fixture 的单项校准执行：ID 为 1..253；方向只能为 -1/+1；soft_min_raw < soft_max_raw <= 1023；center_raw 位于软限位内；max_step_raw 和 speed_limit_raw 为正。
- 511 只可作为装舵盘时的电气量程中点，不能自动成为机械 center_raw。
- 当前 SERVO_GATE_COUNT=2，以上 C 安全门不能外推为八舵机生产执行层。

### 2.3 当前反馈与日志能力

- probe_scs0009.py 是只读工具，可读取型号、角度限位、扭矩、目标/当前位置、速度、负载、电压、温度、运动状态和电流；它不写寄存器。
- host/analyze_servo_log.py 能检查一个会话/试验内 time_ms 不回退、sample_seq 严格递增、读取失败时不夹带“新鲜反馈”等基本一致性。
- 该日志校验器目前固定为 2 个舵机，并且没有舵机 ID、扭矩、电流、运动状态、供电模式、停机事件或 8/8 周期完整性字段，不能直接充当四指验收器。
- validation_reports/four_finger_bringup_session_template_2026-08-16.md 已要求记录固件/源哈希、机械版本、Gate、八角色、供电电压/限流、总线照片和原始证据路径，但它是人工 Markdown 模板，空白和自由文本目前不会自动失败。

### 2.4 当前安全与停止边界

- 单指文档规定只读窗口使用 6.0 V、1.0 A；小幅动作准备阶段曾规定 6.0 V、2.0 A；持续 C.C、明显升温、舵机温度达到 50 °C、卡滞、通信丢失、方向错误、焦味或烟雾均要求立即停止并关闭外部 6V。
- 当前两舵机 C 安全门会因配置无效、未 armed、故障锁存、ID 不匹配、反馈失败/过期、位置/电压/温度越界、目标越界、单步过大或总线写失败而阻断。
- motion monitor 会因未知 ID、读取失败、舵机错误或超时进入失败状态；当前实现仍绑定两舵机。
- 离线执行状态模型含 safe_stop_required、故障锁存和 clear-fault 后保持 disarmed 的语义；这些是模型证据，不等同于 Titan 已接入真实八舵机停机输出。

## 3. 仍未知或未证明（UNKNOWN / BLOCKING）

以下字段不得预填，不得从两舵机 fixture 外推：

| 项 | 当前状态 | 阻断含义 |
|---|---|---|
| 8 个实物舵机的真实 ID 与角色映射 | UNKNOWN | 不能建立生产配置或姿态 |
| 8 个 ID 在同一总线上的唯一性 | UNKNOWN | 仅“记录里不重复”不能排除总线地址冲突 |
| 每个角色的机械方向 | UNKNOWN | 不得预填 direction_sign |
| 每个角色的机械中心和软限位 | UNKNOWN | 不得把 511 或厂内限位直接抄入生产 CSV |
| 每角色允许最大单步和速度 | UNKNOWN | 必须由装配状态下实测与批准产生 |
| 八舵机稳态、启动峰值和堵转趋势 | UNKNOWN | 不能把 1.0 A/2.0 A 单指值当全手限流 |
| 全手电源额定能力、线束压降和连接器温升 | UNKNOWN | 不能授权空载同步或抓握 |
| 8 舵机反馈一整轮的最坏耗时 | UNKNOWN | 不能证明 freshness 门槛对 8 项仍成立 |
| 真实八舵机整组停止策略 | UNKNOWN | 软件 stop/torque-off 不能替代外部 6V 切断 |
| 外部 6V 的唯一、可快速切断路径 | UNKNOWN | 异常恢复 Gate 不能通过 |
| 断电后故障舵机/线束/机构是否受损 | UNKNOWN | 不得在同一会话直接重试 |

## 4. 建议的机器可检查记录边界

建议未来每次现场会话同时保存：

- 人工记录：现有四指验收模板的一份带日期副本；
- 机器记录：validation_reports/raw/<session_id>/bringup_record.json；
- 原始证据：未剪辑终端、供电面板照片/视频、接线/机械照片、只读反馈 CSV；
- 校验结果：bringup_record_validation.json，只能由离线校验器生成。

机器记录必须与生产配置分离。禁止由该 JSON 自动改写校准 CSV、Titan C 或姿态库。

### 4.1 顶层公共字段

以下字段必填；空字符串、null、PENDING、UNKNOWN 均不能通过完成态校验：

| 字段 | 类型/约束 |
|---|---|
| schema_version | 整数，当前建议 1 |
| session_id | 唯一、稳定，不含路径控制字符 |
| record_revision | 正整数 |
| hardware_accessed | 布尔值 |
| operator | 非空字符串 |
| started_at / ended_at | 带时区 ISO-8601，起始不晚于结束 |
| gate_requested / gate_completed | 整数；完成门不得高于实际证据 |
| evidence_level | OFFLINE / LOOSE_BENCH / MOUNTED_SINGLE_FINGER / FOUR_FINGER_GRASP |
| firmware_hex_sha256 | 64 位十六进制 |
| titan_source_sha256 | 64 位十六进制 |
| maix_app_sha256 | 64 位十六进制，或 NOT_USED_WITH_REASON |
| mechanical_revision | 非空、可追溯版本 |
| previous_session_id | 可空；重试时必须引用前一会话 |
| eligible_for_next_gate | 仅由校验器派生，人工 true 无效 |

附加规则：hardware_accessed=false 的记录只能归类为 OFFLINE，不能含现场测量值；出现 stop event 时默认不能晋级。

## 5. 逐指校准记录规则

### 5.1 每个角色的必填字段

每个角色必须分别存在，不能共享一个“整指已校准”布尔值：

- role、servo_id、model_readback、bus_name、baud_rate；
- physical_location_evidence；
- direction_sign；
- direction_trial.start_raw / command_raw / end_raw / observed_mechanical_direction / evidence_path；
- center_raw、center_method、soft_min_raw、soft_max_raw；
- max_step_raw、speed_limit_raw、position_unit_status；
- pre_read_ok、post_read_ok、calibrated、approved_by。

### 5.2 失败关闭规则

单角色只有同时满足以下条件，校验器才可派生 calibrated=true：

1. role 属于固定 8 角色且只出现一次；
2. servo_id 为非布尔整数 1..253；
3. 型号和 ID 有本次会话只读原始证据；
4. direction_sign 只能为 -1/+1，并关联一次可观察、低幅方向试验证据；
5. soft_min_raw < center_raw < soft_max_raw <= 1023；完成态建议严格内含，不接受中心恰好等于软限位；
6. max_step_raw > 0、speed_limit_raw > 0，且来源为本次机械版本下的实测批准；
7. center_method 不能是 ELECTRICAL_MIDPOINT_ONLY；
8. pre_read_ok、post_read_ok 都为真，反馈未过期且无舵机错误；
9. operator 和 approved_by 非空；
10. 本角色相关试验期间没有未关闭的 stop event。

任一字段缺失、单位状态不明确、证据文件不存在、机械版本变化或重新装舵盘后，状态必须回退为 calibrated=false。校准结果不能跨机械版本自动继承。

## 6. 八舵机枚举记录规则

### 6.1 机器字段

枚举记录至少包含：method、expected_roles、expected_ids、8 条 observations、unexpected_ids、missing_ids、duplicate_or_collision_suspected、power_cycle_recheck_passed、complete。

每条 observation 至少包含：role、servo_id、model、read_ok、torque_enabled、voltage_raw、temperature_raw、current_raw、moving、sample_time_ms、evidence_path。

### 6.2 失败关闭规则

- expected_roles 必须恰好等于固定 8 角色集合；observations 必须恰好 8 条。
- role 和 ID 均两两唯一；ID 全部为 1..253。
- unexpected_ids、missing_ids 必须为空；任何通信冲突、重复响应、包解析异常都令 duplicate_or_collision_suspected=true。
- 8 条都必须 read_ok=true、moving=false、torque_enabled=false；缺一项即失败。
- 每条反馈必须属于同一明确采样窗口，并带原始证据；不能拼接历史会话。
- 断电重启后的第二次只读结果必须与第一次的 ID/型号/角色映射一致，才可令 power_cycle_recheck_passed=true。
- 记录中的 ID 不重复只证明文件内部一致；若现场方法不能排除总线地址冲突，complete 仍必须为 false。

## 7. 供电与限流记录规则

### 7.1 现有值的适用边界

6.0 V/1.0 A 是既有单指两舵机只读 Gate 的记录要求；6.0 V/2.0 A 是单指小幅动作准备值。两者都不是八舵机全手额定或安全限流结论。因此四指记录中不能给 current_limit_a 设置默认值。

### 7.2 机器字段

供电记录至少包含：

- logic_power_isolated；
- servo_supply_output_before_gate / servo_supply_output_after_gate；
- servo_voltage_set_v / servo_current_limit_set_a；
- limit_basis / limit_approved_by；
- single_external_servo_power_entry_confirmed；
- wiring_evidence_path / supply_panel_evidence_path / output_off_evidence_path；
- mode_samples：time_ms、CV/CC、voltage_v、current_a；
- peak_current_a / peak_measurement_method；
- sustained_cc_observed / connector_or_wire_heating_observed。

### 7.3 失败关闭规则

- 只要本 Gate 使用舵机外部电源，电压、限流、批准依据、供电入口、面板证据和结束 OFF 证据全部必填。
- current limit 不得由软件模板默认产生，必须关联 limit_basis 和 limit_approved_by。
- sustained_cc_observed=true、任何发热、线束/连接器异常或供电入口不唯一时，本 Gate 必须失败并生成 stop event。
- 电源面板瞬时显示不能自动证明峰值电流；未说明仪器/采样方式时 peak_current_a 必须保持 null。
- “结束时软件已 disarm/torque-off”不能代替 servo_supply_output_after_gate=OFF 的外部电源证据。

## 8. 异常停机与结束状态记录规则

### 8.1 必须区分正常结束和紧急结束

正常结束可以按计划先确认扭矩关闭，再关闭外部 6V。紧急情况的优先级是外部 6V 立即切断；此时断电后无法再读取 torque=0，不能为了补记录重新上电。因此机器格式必须允许“最后一次扭矩状态未知，但外部电源已切断”，且不能把它误判为正常通过。

### 8.2 stop event 字段

每个 stop event 至少包含：

- event_seq、detected_at_ms；
- trigger（HEATING / SUSTAINED_CC / STALL / COMMS / WRONG_DIRECTION / SMELL_SMOKE / OTHER）；
- trigger_source（OPERATOR / SUPPLY / SERVO_FEEDBACK / SOFTWARE）；
- affected_roles、last_feedback_evidence_path；
- software_disarm_attempted、software_disarm_result；
- external_power_off_commanded_at_ms、external_power_off_confirmed_at_ms、external_power_off_evidence_path；
- normal_closeout、fault_latched、same_session_retry_count、inspection_required、review_disposition。

### 8.3 失败关闭规则

- event_seq 严格递增，时间不得回退；确认断电时间不得早于触发时间。
- 确认断电时间或证据路径缺失时，状态为 POWER_OFF_UNCONFIRMED，禁止下一 Gate。
- 紧急事件后 same_session_retry_count 必须为 0；任何重试必须新建 session，并引用前一 session 和审查结论。
- fault_latched=true 时不能通过“重新 arm”清除证据；必须记录独立 review disposition。
- 通信丢失或脚本崩溃时，不能把“没有继续收到数据”解释为舵机已停。
- 软件 disarm、torque-off 或 stop 发送失败/未知时，外部 6V 断开仍是必要结束证据。
- 对发热、焦味、烟雾、连接器变色、线束软化或持续 C.C，必须 inspection_required=true；完成检查前 review_disposition=BLOCKED。

## 9. Gate 派生规则

机器校验器应派生 Gate 结论，不接受人工直接写 PASS：

| Gate | 最低机器证据 | 任一失败时 |
|---|---|---|
| 0 | 机械版本、齐套清点、断电照片、供电入口照片 | 保持 gate_completed=-1 |
| 1 | 本次会话只读记录、扭矩关闭、无运动、正常断电 | 不得安装后续动作件 |
| 2/3 | 官方顺序证据、装配照片、机械版本更新 | 全部校准状态失效 |
| 4 | 对应单指两角色各自通过第 5 节，且无未关闭 stop event | 该指仍未校准 |
| 5 | 8/8 通过第 6 节，供电记录通过第 7 节 | 禁止整组写包 |
| 6 | 8/8 新鲜反馈、整组目标/观测 ID 集一致、停止链已验证 | 禁止同步动作 |
| 7 | Gate 6 已通过且本次单物体证据完整 | 不得声明抓握成功 |

Gate 必须单调前进；机械重新拆装、换舵机、改 ID、换线束/电源路径、校准文件变化或固件变化，都必须显式使受影响 Gate 失效，不能沿用旧 PASS。

## 10. 正常、失败和集成边缘检查

### 正常路径

8 个角色/ID 唯一；8/8 只读成功；扭矩关闭；每个校准字段有本次证据；供电设置和正常结束 OFF 证据完整；无 stop event。结果才可允许进入下一 Gate。

### 失败路径

7/8 只读成功、一个反馈超时；即使另外 7 个全部正常，也必须输出 ENUMERATION_INCOMPLETE，且 eligible_for_next_gate=false。

### 集成边缘

运动中通信丢失，同时无法确认 torque-off。记录必须保留最后反馈、生成 stop event、要求外部电源 OFF 证据，并把结果标成 BLOCKED，不能因后续 UART 恢复自动通过。

## 11. M2×18 到货后仍需真机验证

1. M2×18 数量、长度、螺纹型别与每指实际装配适配；
2. Frame-2/指壳/拉杆/舵盘版本及官方装配方向；
3. 每个舵机实物位置、真实 ID、型号与断电重启后的重复读回；
4. 同总线 8 ID 唯一性和无意外响应；
5. 每个角色实际开合方向、电气中点装盘后的机械中心、双侧软限位；
6. 每角色低幅安全步长、速度上限、反馈新鲜度和到位容差；
7. 外部 6V 唯一入口、地线/线序、连接器和线束压降/温升；
8. 单指只读/小幅时电流，以及 8 舵机分阶段上电、空载同步时的稳态与瞬态电流；
9. 全手限流值和电源容量是否足够，C.V/C.C 转换是否符合预期；
10. 任一 1/8 反馈失败、ID 错误、总线超时、温度/电压越界时是否整组 fail-closed；
11. 软件 disarm/torque-off 失败时，外部 6V 切断是否可靠且现场可执行；
12. 异常停机后机构、舵机、线束和连接器检查，以及新会话重新准入。

在上述项目分别留下原始证据并通过审查前，不得生成生产八舵机校准 CSV、生产姿态库，也不得声称完成四指动作或抓握。

## 12. 最小后续实现建议

1. 先冻结 JSON 字段和派生规则，新增纯离线校验器与正常/失败/集成边缘测试；
2. 再让现场 Markdown 模板引用 session ID 和 JSON 路径，避免双份自由文本漂移；
3. 将现有两舵机反馈 CSV 规则扩展为“显式 count + 8 角色”，并补 ID、torque、current、moving、power mode 和 stop event；
4. 只有在八舵机生产安全链完成并通过离线测试后，才讨论从验收记录人工审核迁移到生产校准文件；不得自动迁移。

权衡：双文件（Markdown + JSON）会增加一次填写成本，但能显著降低空白被误判为 PASS、不同会话证据拼接、单指电源参数外推到全手，以及紧急断电后为补 torque=0 重新上电的风险。

## 13. 本批合规声明

- 新增文件：docs/FOUR_FINGER_BRINGUP_RECORD_RULES_AUDIT_2026-08-16.md。
- 未修改生产代码、协议、CRC、Titan C、Maix 生产代码、校准 CSV、姿态库或 D 盘工程。
- 未修改 host/four_finger_config_rules.py 及其测试。
- 未打开串口、未枚举设备、未接线、未上电、未烧录、未移动舵机。
- hardware_accessed=false。
