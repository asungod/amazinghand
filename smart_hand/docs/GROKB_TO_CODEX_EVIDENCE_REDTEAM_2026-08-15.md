# grokB → Codex 主模型交接（证据红队与无机械展示包，2026-08-15）

- 发件：grokB
- 收件：Codex 主模型
- 任务：`AUX_MODEL_TASK_BOARD` 中「Grok B：证据红队与比赛展示包」
- `hardware_accessed=false`
- 未改生产代码、协议、校准 CSV、D 盘工程
- 未改 Claude A 的装配 Gate/Runbook，未写 Grok A 的 STATUS 提案

请先读本文件，再决定是否把 README 补丁落地、是否把本包定为赛场唯一脚本。

## 1. 交付物

| 路径 | 作用 |
|---|---|
| `docs/GROKB_EVIDENCE_REDTEAM_2026-08-15.md` | 混淆句清单 + README/长稳报告最小修正提案 |
| `competition_2026/NO_MOTION_DEMO_PACK_2026-08-15.md` | 3 分钟无动作演示、异常恢复讲稿、附件清单 |
| `competition_2026/evidence/evidence_index.csv` | 新增 `E0007`；`E0003`/`E0006` 加互斥注释 |
| `competition_2026/README.md` | 同步 YOLO 长稳、INTENT/LOCKED 边界、装框未动作、到货前只演阶段 B |
| 本文件 | 给 Codex 的审查入口 |

## 2. 必须采信的红队结论

1. 屏幕 `INTENT` = Maix 按 `class_id` 本地映射，**不是** Titan `sh_status`。
2. 屏幕 `MOTION LOCKED` = `main.py` 写死字符串，**不是** 安全门遥测。
3. ACK / `accepted` / `actionable=0` **不是** 舵机执行。
4. `E0006` 是 Mock 十秒；`E0007` 是真实 YOLO 瓶子长稳。禁止合并。
5. `infer_fps=100.0` 禁止当相机/NPU 帧率引用。
6. RNDIS「约 30 分钟无新重置」≠ 视觉 30 分钟耐久；长稳下限是约 15 分 23 秒。
7. `E0007` 是工程 `recorded`，不是竞赛冻结：未剪辑日志、录像、模型哈希仍缺（`E0003`）。
8. cup/remote 真实摄像头长稳 `UNVERIFIED`。
9. 散置 `E0002` 与「已装框、无舵盘/连杆、M2x18 待到货」不是同一层。
10. 旧 `COMPETITION_PITCH_AND_STORYBOARD.md` 仍写未烧录/抓握近景，**赛场不得用**；以无机械展示包为准。

## 3. 本批未改、请 Codex 裁决是否落地

README 高危句（红队 R1–R6）**未直接改** `smart_hand/README.md`，避免与 Claude A 机械一致性撞车。建议 Codex 合并后落地，至少改：

- 「无舵机长稳闭环」→「无舵机 UART/ACK 长稳」
- 「舵机必须保持断开」→「已装框，但不接 Titan/Maix、不上 6V、不装舵盘/连杆」

`DEMO_MVP_RUNBOOK.md` 阶段 A 仍把 mock 写成首次实验室验收，建议标历史。

## 4. 离线检查

本批只改 docs / `competition_2026` / 证据索引，未跑 `run_all_checks.ps1`（无生产代码变更）。  
`E0007` 的 `source_sha256` = 长稳报告  
`B01DF9448B3F7CA89E350262408F84FDABE0D8CF83170E92708B5281AA5A6E91`。

## 5. 给 Codex 的 10 行审查提示

1. `INTENT`/`MOTION LOCKED` 解释是否允许上赛场？
2. `E0007` 是否保持 `recorded` 且不关闭 `E0003`？
3. 是否批准把无机械展示包定为当前唯一评委脚本？
4. README R2（断开 vs 已装框）是否由你或 Claude A 落地？
5. 是否禁止任何辅助模型在 M2x18 到货前授权 `center_hold`/`finger_smoke`？
6. 是否要求用户补采未剪辑终端+屏幕录像，还是先用口头演示？
7. 旧 90 秒抓握讲解是否标 `FUTURE` 以免误用？
8. 本包未授权任何真机步骤，下一批仍由你批准。
