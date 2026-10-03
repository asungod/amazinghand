# DeepSeek → Codex 交付：Titan D2「TX 超时后总线永久静默」修复

日期：2026-09-23
前置：D1 已审核通过（`DEEPSEEK_TO_CODEX_TITAN_UART_D1_FIX_2026-09-22.md`）

**约束遵守**：未集成语音模块，**未烧写**。

---

## ⚠️ 烧写前必读：工程根目录那个 hex 是旧的

与 D1 报告同一件事，此处再列一次，因为**刷错比补丁本身更容易出事**：

| 路径 | 状态 | SHA-256 | 时间 |
|---|---|---|---|
| `titan_uart_test\Debug\rtthread.hex` | ✅ **构建产物，认这个** | `d4aae9a3d4aeca76c26227f8058030b556deec5c7a59d778f0d6d8972ee1ab5e`（含 D2） | Sep 23 00:12 |
| `titan_uart_test\rtthread.hex` | ⛔ **陈旧，勿用** | `121262e133e6a54f3baf7d32204fbabf52f6ede367e4e00e9c165697e28db016` | Sep 21 12:52 |

两份同名文件来自两套构建系统：CDT/make 产物落 `Debug/`，SCons 的 `POST_ACTION` 在工程根再生成一份，互不覆盖。**已写入 `TITAN_VOICE_MODEL_REPRODUCE.md` 的烧写章节。**

---

## 1. 实际修改文件

| 文件 | 改动 |
|---|---|
| `D:/Micu/.../src/servo_group_readonly.h` | 新增 `aborted_cycles` 计数 + `servo_group_readonly_abort_cycle()` 声明 |
| `D:/Micu/.../src/servo_group_readonly.c` | 新增 `abort_cycle()` 实现 |
| `D:/Micu/.../src/servo_bus_readonly_rt.c` | `run_one_cycle()` 两条故障路径改为先 abort 再返回 |

原始副本与 diff 在 `tmp/d2fix/`（`.orig` / `.patched` / `.diff`）。

---

## 2. 根因（比你描述的更微妙一层）

`servo_group_readonly_note_tx_failed()` **本身不是"结束周期"**：

```c
void servo_group_readonly_note_tx_failed(servo_group_readonly_t *group)
{
    if (group != NULL && group->cycle_active &&
        group->transaction.state == SCS0009_TXN_WAIT_STATUS)
    {
        scs0009_transaction_abort(&group->transaction);
        finish_current(group, 0);          /* ← 这里是推进，不是结束 */
    }
}
```

`finish_current(group, 0)` 只把 `current_index++`，**只有轮到最后一个索引才置 `cycle_active = 0`**。

于是 `run_one_cycle()` 里三条 TX 相关路径的语义**各不相同**：

| 路径 | 原行为 | 判定 |
|---|---|---|
| `R_SCI_B_UART_Write` 返回非 `FSP_SUCCESS` | `note_tx_failed()` + `continue` | ✅ **本来就正确**——推进到下一个舵机，最后自然结束 |
| `prepare()` 返回 0 | `return` | ❌ `cycle_active` 永久留 1 |
| TX 20 ms 超时 | `return` | ❌ 同上（**这条是活的缺陷**，见 §4） |

而 `begin_cycle()` 的前置条件包含 `cycle_active` 非零即拒绝 ⇒ **一次故障后舵机总线到重启前永久静默**（`g_ready` 冻结旧值、`publish_cycle()` 再也不跑、所有 SIGN/TRAIN/恢复动作永久失败）。

---

## 3. 修法

新增 `servo_group_readonly_abort_cycle()`：结束周期、清 `cycle_active`、置 `cycle_complete = 0`（**无有效数据可发布**）、`failed_reads++`、按需 `transaction_abort` + `reset`、`aborted_cycles++`。

**计数器刻意不复用 `invalid_cycles`**：后者语义是"周期完成了但数据不可信"，而中止的周期**根本没产生数据可判断**。混用会让遥测失去区分能力。

两条故障路径改为 `abort_cycle` + `return`；write-failure 路径**原样未动**。

TX 超时那条**不能**简单改成 `continue`：它位于**内层** `while`（等待 `tx_src_bytes`/`TEND`）里，`continue` 只会继续内层循环；而且一次 20 ms 发不完说明总线没在排水，逐个舵机继续超时只会把 20 ms 放大 N 倍。

---

## 4. ⚠️ 可达性发现：两条路径里**只有一条是活的**

集成测试（`test_run_one_cycle_d2_c.c`）在构造路径 A 的触发条件时发现：**任务书里设想的控制点走不通，而这条路径在生产上很可能根本不可达**。我独立核实了这个论证：

1. `begin_cycle()` 的前置条件包含 `transaction.state != SCS0009_TXN_IDLE` → 返回 0 → `run_one_cycle` **在函数开头就 `return`**，根本到不了 `prepare()`；
2. `prepare()` 的另一半失败条件是 `scs0009_build_read()` 返回 0，而 `servo_group_readonly_init()` 已校验 `1 ≤ id ≤ SCS0009_MAX_ID`，生产上 id 恒合法；
3. `finish_current()` 每次都 `scs0009_transaction_reset()`，事务在下一轮外层循环前已回到 IDLE。

**结论**：

| 路径 | 生产可达性 | 修复性质 |
|---|---|---|
| **TX 20 ms 超时** | ✅ **可达**（总线未排水时） | **真实缺陷修复** |
| `prepare()` 返回 0 | ❌ 按现有源码不可达 | **纵深防御**（若将来可达，不会再卡死） |

**请勿把本次修复记作"消除了一个已观测到的线上故障"。** 准确表述是：**修掉了一条可达的卡死路径，并顺手堵住了另一条目前不可达的同类路径。**

测试构造路径 A 用的是"把 `g_group.ids[0]` 置成超出 SCS0009 id 空间的值让 `build_read` 拒绝"，这验证了**接线正确**，但没有证明该分支在真机上会被触发。

---

## 5. 测试与变异

### 5.1 纯逻辑层（状态机本身）

`smart_hand/tests/test_servo_group_recovery_c.c` + `.py`，**7 用例全过**：

abort 清标志 / **abort 后下一周期 `begin_cycle()` 返回 1（可恢复）** / abort 幂等 / NULL 安全 / 周期中途 abort / WAIT_STATUS 下 abort / **`note_tx_failed` 语义未被改变**。

变异（**我独立复做**）：不清 `cycle_active`（=修复前行为）→ EXIT=3；abort 变空操作 → EXIT=3。

### 5.2 接线层（`run_one_cycle` 是否真的调了 abort）

`smart_hand/tests/test_run_one_cycle_d2_c.c` + `.py`，**4 用例 / 134 断言全过**：

| 用例 | 断言要点 |
|---|---|
| 0-harness-selfcheck | **反空转底线**：桩的 `CSR_b.TEND` 必须落在 bit 30（对应真实头文件位序）；干净周期真的发 8 个请求、读 112 字节 RX、publish 8 个样本 |
| 1-prepare-zero-aborts | 先证明走的是 A（`write_calls==0`）；`cycle_active==0`、`aborted_cycles==1`、`completed_cycles==0`；**`begin_cycle()==1`** |
| 2-tx-timeout-aborts | 取证 `write_calls==1`、`yield_calls>=20`、真超时；`cycle_active==0`、`aborted_cycles==1`、`current_index==0`（整周期结束而非推进）；**`begin_cycle()==1`** |
| 3-write-failure-does-not-abort | **对照**：8 次 Write 逐次取证"失败后确实推进到下一个舵机"；`aborted_cycles==0`、`completed_cycles==1` |

变异：子 agent 做了 4 个（两条路径各还原成裸 `return`、把 A 换成 `note_tx_failed`、把 C 反向换成 abort），**全部被抓**。**我另独立复做了 TX 超时那个**（不经它的脚本）：

```
变异体退出码: 1
[case] 2-tx-timeout-aborts-and-recovers: FAILED (23 checks)
FAIL 4 of 134 checks failed
```

### 5.3 诚实边界（子 agent 自列，我认同）

- **抓不住打桩层语义**：真实的 `R_SCI_B_UART_Write` 是否先置 `tx_src_bytes` 再靠 ISR 清零、`CSR.TEND` 在 1 Mbps 下的真实时序、`rt_device_read` 多线程行为——全由桩定义，**桩错了测试照样绿**（唯一自检是 bit 30 位序）。
- **抓不住并发**：`g_snapshot_mutex` 在本测试里只做了配对计数，对"锁覆盖范围够不够"无判断。
- **抓不住真实舵机应答**：RX 帧是合成的合法帧，不覆盖坏校验和/错 id/坏长度/应答超时。
- **抓不住时序细节**：abort 在 `set_leds` 之前还是之后、`drain_servo_uart()` 放前放后——断言只看终态。
- `run_one_cycle` 里**没走到**回显抑制的"整包完全匹配被吞掉"那一半（回环模型不产生整包回显）。
- `servo_bus_readonly_rt.c` 1681 行里**只走了 `run_one_cycle` 及其下游**；其余（线程入口、pair/group/index/rehab/sign 各路径、全部对外 API）未执行。

---

## 6. 构建结果

```
make 退出码 0；servo_bus_readonly_rt.c 与 servo_group_readonly.c 均重编译，零告警
（日志里唯一告警是 `smart_hand_uart.c:777 'sh_status' defined but not used`，为既有告警，因 FINSH 关闭）

               text      data       bss
D1 之前      125676      1024    137200
D1 后        125668      1024    137204
D2 后        125804      1024    137204      (+136 text，bss 不变)

Debug/rtthread.hex  d4aae9a3d4aeca76c26227f8058030b556deec5c7a59d778f0d6d8972ee1ab5e
```

---

## 7. 尚未完成的真机验证

未烧写。集成刷写后需验证（与 D1 合并进行）：

1. 冷启动 20 次，每次均重建 UART ACK；
2. 舵机总线轮询与手势动作正常；
3. **制造一次真实的 TX 超时**（例如在总线忙时启动一次周期）后，确认**下一周期能自动恢复**而不是永久静默——这是 D2 修复的直接验收点，主机侧无法替代；
4. 无断言、无永久离线、无新增 RX 错误。

---

## 8. 遗留（**不在本补丁内**，建议单独立项）

D1 排障时发现的 servo 模块另两处，本次**未改动**：

1. `g_servo_pair_commission_result` 被六条路径共用，理论上一次成功的 group/pair commission 会让上位机收到**从未发生的 TRAIN SUCCEEDED**；
2. pair/group/index 四条分支在**无忙标志**的情况下调用长阻塞函数，使 `servo_bus_rehab_demo_request()` / `servo_bus_sign_demo_request()` 在运动期间仍回 `ACCEPTED` 而非 `BUSY`。

另外 `eight_servo_safety_gate` 的 `arm / plan_once / note_bus_write / clear_fault` **全工程无调用点**，导致 `servo_bus_safety_gate_armed()` 恒返回 0——属功能缺口/死代码，非次序类缺陷。
