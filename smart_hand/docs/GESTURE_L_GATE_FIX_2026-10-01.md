# Grok 证据复验与 L 候选竞争修复（2026-10-01）

## 范围与结论

本轮仅修改主机工作区的 MaixCAM2 规则分类器及其测试；未连接设备、未烧录 Titan、未触发机械动作、未调用真实云模型、未同步部署候选目录。

先独立复跑 Grok 原始包：7/7 案例与记录一致，原始 11 项测试通过。输入全部为正交投影模拟，设备样本数为 0，不能用于宣称真机识别准确率。

修复一条明确的规则竞争缺陷：V 原型的指尖距离加分可使“中指已折叠”的 V 候选排名第一；它随后通不过 V 门槛，但原逻辑直接返回 UNKNOWN，忽略已经完全满足 L 门槛的候选。

现在仅在最高候选为 V、且 L 满足全部既有门槛时选择 L，并返回 L 的分数。L 的食指、其余三指、拇指与最低分数门槛均未放宽；没有任意候选逐级兜底，没有改变稳定计时或通信/动作门控。

## 证据保留与测试含义

`outputs/Grok_Gesture_Review_2026-10-01/cases.json`、`reproduce.py`、`README.md` 保持原样。

修复前分类器及原始 11 项测试备份于该目录的 `pre_l_gate_fix/`：

- 分类器 SHA-256：`FDAFDDAC78EF937AF8817000CB749E2FEEFEDB3768651127CDB78D9D3A370EF0`
- 原始测试 SHA-256：`6EFFB31B80D96632D8E9A425B7ED8F936864D87FDFCB8C7C6D9628228FAF1CF9`

生产测试文件中 3 个受影响的方法明确改为修复期望，原有另外 8 个方法仍记录未变行为；另加 3 个方法覆盖门槛不放宽、镜像/缩放/平移、真实未知帧仍重置稳定计时。共 14 个方法。

新验证脚本 `verify_l_gate_fix.py` 会：

1. 用冻结分类器运行原始测试，确认 11/11 通过。
2. 用冻结分类器重放原始 JSON 全部记录字段，确认 7/7 匹配。
3. 比较冻结与当前分类器实际输出：仅 UNKNOWN→L_SHAPE 一组改变，其他 6 组完整结果不变；7 项原型分数均不变。
4. 运行当前 14 项测试，并将冻结分类器代入同一套测试，确认 5 个相关方法拒绝旧行为。

原始 `reproduce.py` 是“旧输出快照匹配器”，不是修复验收规范。修复后对当前源码运行它会因侧转 L 一组变化而返回非零；不能改写 JSON 观测值来制造 7/7。

## 复跑命令与结果

以下命令从项目根目录 `C:\Users\zzh\OneDrive\Desktop\PCBBOM\嵌赛物联网` 执行：

```powershell
python -X utf8 outputs/Grok_Gesture_Review_2026-10-01/verify_l_gate_fix.py
python -X utf8 -m unittest smart_hand.tests.test_ai_course_advice_proxy smart_hand.tests.test_web_stream smart_hand.tests.test_sign_core smart_hand.tests.test_sign_integration smart_hand.tests.test_maix_main smart_hand.tests.test_protocol smart_hand.tests.test_live_sidecar smart_hand.tests.test_gesture_misclassification_evidence -q
```

结果：验证脚本退出 0，相关 141 项主机测试通过。Python 编译检查通过。上述测试使用本地替身，不验证云端 API 可用性或真实硬件性能。

## 源码与部署状态

- 当前工作区分类器 SHA-256：`F45D6B447EE28EBE5BB2BF6DCF22E856498B62D4867CC8A2CCEE5C116135F575`
- `outputs/OpenSignHand_Hardware_Bringup_2026-09-21/maixcam2/gesture_classifier.py` 未同步，仍为修复前哈希 `FDAFDDAC...A370EF0`。
- 因此运行旧候选目录或设备上的旧程序不会得到本次修复；不能将本次主机结果当作已部署结果。
- 可用 `git diff --no-index` 对照备份与当前源码；这些文件目前为未跟踪文件，普通 `git diff --check` 不能证明其新增内容无空白问题。

## 仍未解决与下一步

模拟松弛 V→OPEN_PALM，以及投影拇指弯曲的 L→POINT 均保留原输出。前者说明二维路径伸直度可掩盖关节折返，后者说明投影可能损失拇指伸展证据；两者不能靠降低拇指门槛或硬塞标签安全解决。

下一步采集真机误判时的 21 个关键点及目标姿势，覆盖左右手、正对/侧转、远近、正常张掌与正常指向对照；记录关节角与置信度。评估 OPEN 的关节角拒绝条件时必须同时测量真实张掌的误拒率。还需真机验证本次 L 修复是否改善训练，不宣称模拟结果等于实机效果。
