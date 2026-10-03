# Boot/Session 协议扩展草案

## 状态

这是尚未实现的协议 v2 草案，用于解决 Maix 在 Titan 的 1.5 秒离线门限内快速重启
时，发送序号从 0 开始但 Titan 仍保留旧序号基线的问题。当前部署中的 Python/C
解析器不接受 `HELLO`，Titan 基线没有修改。

## 拟议帧

```text
$HELLO,SEQ,BOOT_ID,VERSION,CAPABILITIES*CRC
```

- `SEQ`：HELLO 本身的 16 位序号，建议每次进程启动从 0 开始。
- `BOOT_ID`：本次 Maix 进程/启动会话的 32 位非重复标识。
- `VERSION`：本草案使用 2。
- `CAPABILITIES`：32 位能力位图；首版可为 0，定义后再启用位。

## Titan 拟议行为

1. 收到受支持版本且 `BOOT_ID` 与当前不同的合法 HELLO：保存新会话，重置序号基线，
   清除旧视觉目标并撤销动作授权，然后 ACK status=0。
2. 收到同一 `BOOT_ID` 的重复 HELLO：ACK status=0，但不得再次重置已经推进的序号
   基线，避免旧 HELLO 重放回退状态。
3. 版本不支持：ACK status=2，不改变当前会话、目标或序号基线。
4. 未建立会话时的 v2 VISION 不得授权动作。
5. 同一会话内继续使用半范围规则判断 16 位序号新旧，允许 65535 到 0 回绕。

## 启动与兼容顺序

1. Maix 启动后先发送 HELLO，收到成功 ACK 后再发送 PING/VISION。
2. HELLO 超时时允许重发同一 BOOT_ID；重发不能创建多个会话。
3. v1 Titan 会把 HELLO 当未知类型丢弃，因此 v2 Maix 必须有明确的兼容/降级配置，
   不能在没有协商结果时假定 Titan 已清除旧目标。
4. 两端升级必须在当前 v1 基线完成真机验收后同时进行，不能只更新一端。

## 尚需真机确认

- MaixPy 是否提供适合生成 32 位 BOOT_ID 的随机源；若没有，需要设计低磨损的持久
  启动计数。仅用 `ticks_ms` 可能在相似启动时刻碰撞。
- UART 驱动在进程重启时是否会残留发送缓冲。单 TX 线路通常保持字节顺序，但仍需
  实测 HELLO 前后不会混入旧会话尾帧。
- STATUS/能力位和协议降级的最终编码。

BOOT_ID 碰撞会让 Titan 把新启动误认为旧会话，因此实现前必须解决生成策略，不能
把本参考模型直接移植到 Titan。

## 测试向量

`SESSION_TEST_VECTORS.json` 覆盖新会话、重复 HELLO、旧序号、新 BOOT_ID、版本不
支持和序号回绕。主机参考模型位于 `host/session_sequence_model.py`，验证命令：

```powershell
python -m unittest tests.test_session_sequence_model -v
```
