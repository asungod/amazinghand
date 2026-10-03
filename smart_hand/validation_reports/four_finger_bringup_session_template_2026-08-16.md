# 四指到货后现场验收记录模板

**状态**：TEMPLATE_ONLY / hardware_accessed=false（填写前）  
**用途**：M2×18 到货后的现场记录；不代表已授权动作。

## 0. 现场门禁

- 日期/操作者：
- 固件 hex SHA-256：
- Titan 工程/规范源 SHA-256：
- Maix 版本、模型文件与哈希：
- 机械版本/Frame-2 版本：
- M2×18 数量：____（每指需求 2 根）
- M2 L25、手指机构、柔性指壳、Custom horn、M2×10/螺母/垫圈：逐项清点并拍照
- 外部 6V：OFF（进入 Gate 0 前必须保持）
- 校准 CSV：空表头 / 已批准版本（不得现场猜填）

## 1. Gate 顺序

| Gate | 条件 | 结果 | 证据文件 | 停止/回退原因 |
|---|---|---|---|---|
| 0 | 断电、零件齐套、装框照片与官方方向一致 | PENDING | | |
| 1 | 不动作只读复核：ID/型号/总线/供电隔离 | PENDING | | |
| 2 | 按官方顺序完成机构、拉杆、link | PENDING | | |
| 3 | 电气中点下安装舵盘 | PENDING | | |
| 4 | 单指低幅、方向、中心、软限位 | PENDING | | |
| 5 | 四指 ID/总线/供电逐项确认 | PENDING | | |
| 6 | 空载四指同步小步 | PENDING | | |
| 7 | 单物体一次抓握 | PENDING | | |

任何 Gate 出现发热、焦味、堵转、电流异常、通信丢失或方向不明，立即停止，外部 6V 断开，记录原因并回退到文档审查。

## 2. 八角色现场记录

| 角色 | 实物位置/舵机 ID | 型号 | 方向 | 中心 raw | 软限位 raw | 读回正常 | 校准证据 |
|---|---|---|---|---:|---:|---|---|
| F1_PROXIMAL | 待现场确认 | 待确认 | 待确认 | 待测 | 待测 | PENDING | |
| F1_DISTAL | 待现场确认 | 待确认 | 待确认 | 待测 | 待测 | PENDING | |
| F2_PROXIMAL | 待现场确认 | 待确认 | 待确认 | 待测 | 待测 | PENDING | |
| F2_DISTAL | 待现场确认 | 待确认 | 待确认 | 待测 | 待测 | PENDING | |
| F3_PROXIMAL | 待现场确认 | 待确认 | 待确认 | 待测 | 待测 | PENDING | |
| F3_DISTAL | 待现场确认 | 待确认 | 待确认 | 待测 | 待测 | PENDING | |
| F4_PROXIMAL | 待现场确认 | 待确认 | 待确认 | 待测 | 待测 | PENDING | |
| F4_DISTAL | 待现场确认 | 待确认 | 待确认 | 待测 | 待测 | PENDING | |

禁止把“待测/待确认”替换成猜测值；没有读回和照片证据就保持 `PENDING`。

## 3. 供电与通信记录

- Titan/Maix 逻辑电源：独立供电，电压：____ V
- 舵机外部 6V：____ V，限流：____ A，开启 Gate：____
- 总线拓扑/线序照片：____
- UART2 ACK 基线：sent ____ / acked ____ / pending ____ / timeout ____
- STATUS：link ____ / vis ____ / stale ____ / submit ____ / gate ____
- 证据层级：`LOOSE_BENCH` / `MOUNTED_SINGLE_FINGER` / `FOUR_FINGER_GRASP`

## 4. 结论

- 当前最高通过 Gate：
- 是否允许下一 Gate：YES / NO
- 失败原因及回退动作：
- 原始日志/照片/视频路径：
- `hardware_accessed=true` 仅在实际接线、上电或动作后填写；不得事后补写。
