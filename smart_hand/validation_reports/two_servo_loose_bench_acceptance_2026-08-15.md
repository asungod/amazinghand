# 两舵机散置台架验收记录（2026-08-15）

## 1. 结论

两颗 Feetech SCS0009-C001 在不安装舵盘、连杆和手指机构的散置状态下，完成了 PC 端总线只读、ID1 单向限位恢复、ID1 可逆小步动作，以及 ID1/ID2 同步小步动作与返回。测试结束时两颗舵机扭矩均为关闭状态，用户随后关闭了外部 6V 电源。

本次结果证明散置台架上的通信和低幅动作链路可用；不证明机械中心、安装方向、机械软限位、负载能力、完整单指动作、Titan 舵机执行层或生产抓握姿态已经验证。

## 2. 证据来源和硬件边界

- 物理操作与观察：用户现场执行并回传终端输出和“无异常”观察。
- 本报告：主模型在硬件断电后离线整理，未自行访问硬件。
- 转接板：Waveshare Bus Servo Adapter (A) V1.1，跳帽位于 B（USB-SERVO），串口为 COM4。
- 舵机总线：外部稳压电源 6.0V，限流 1.0A；只使用一个外部舵机电源入口。
- Type-C：连接电脑，仅承担 USB 数据/控制。
- 两颗舵机：散置、无舵盘、无连杆、无遮挡。
- Titan Mini、MaixCAM2：不参与本次舵机控制。
- 测试过程中用户报告无异常声音、无明显发热、无卡滞。

## 3. 离线回归基线

执行：

```powershell
pwsh -File smart_hand\host\run_all_checks.ps1
```

结果：退出码 0；`Ran 239 tests ... OK`，全部 C 测试和 Studio 同步检查通过。

## 4. ID1 下限恢复

此前 ID1 的位置/目标接近原始值 21，而舵机配置下限为 20。旧的小步测试曾要求目标 0，实际会被舵机内部限位钳制，因此不能据此判断舵机损坏。

执行：

```powershell
python smart_hand\host\nudge_scs0009.py --port COM4 --id 1 --delta 16 --speed 50 --loose-servo-confirmed --limit-recovery-confirmed
```

关键输出：

```text
START: ID=1 model=1284 position=21 target=37 limits=20..1003 mode=one-way limit recovery voltage=6.0V temperature=23C
MOTION: reached=36; recovery leaves shaft away from limit
PASS: one-way inward limit recovery verified; torque will be disabled.
```

恢复后只读状态：ID1 `goal=37 position=37 torque=0 temperature=24 current=0`；ID2 `goal=46 position=46 torque=0 temperature=22 current=0`。

## 5. ID1 正常可逆小步

执行：

```powershell
python smart_hand\host\nudge_scs0009.py --port COM4 --id 1 --delta 8 --speed 50 --loose-servo-confirmed
```

关键结果：ID1 从 37 到 45，再返回 38；脚本报告 `PASS` 并关闭扭矩。

随后只读：ID1 `goal=38 position=38 torque=0 temperature=24 current=0`；ID2 `goal=46 position=46 torque=0 temperature=22 current=0`。

## 6. 两舵机同步小步与返回

执行：

```powershell
python smart_hand\host\sync_nudge_scs0009_pair.py --port COM4 --delta 8 --speed 50 --loose-servos-confirmed
```

关键输出：

```text
START: {1: 38, 2: 46}
TARGET: {1: 46, 2: 54}
REACHED: {1: 47, 2: 53}
RETURNED: {1: 39, 2: 47}
PASS: synchronized pair motion and return verified.
```

## 7. 最终安全状态

最终只读结果：

```text
ID1 model=1284 min=20 max=1003 torque=0 goal=39 position=39 speed=0 load=0 voltage=60 temperature=24 moving=0 current=0
ID2 model=1284 min=20 max=1003 torque=0 goal=46 position=46 speed=0 load=0 voltage=61 temperature=22 moving=0 current=0
PASS: found both IDs
```

用户确认外部电源已关闭。两颗舵机最终均 `torque=0`，本轮没有机械动作授权遗留。

## 8. 已通过与未通过

已通过：

- ID1/ID2 总线发现与只读状态；
- ID1 从已配置下限附近向内的单向恢复；
- ID1 散置状态小幅往返；
- ID1/ID2 散置状态同步小幅移动与返回；
- 测试结束扭矩关闭和外部 6V 断电。

仍未通过：

- 舵机安装到 Finger Frame 后的固定可靠性；
- 舵盘方向、机械中心和连杆相位；
- 两颗舵机各自真实安全最小值、中心值、最大值；
- 机构负载下的温升、电流、卡滞和碰撞测试；
- `center_hold_scs0009_pair.py` 的框架安装测试；
- `finger_smoke_scs0009.py` 的完整单指测试；
- Titan/Maix 对舵机的控制；
- 生产校准 CSV 与生产姿态。

## 9. 提交证据限制

本报告是用户真机终端输出的工程归档，不包含未剪辑视频、完整终端截图和电源设置照片。因此可用于内部推进与故障复盘，但在竞赛材料中引用前仍应补齐原始附件。
