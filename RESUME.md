# AmazingHand 继续开发入口

快照日期：**2026-10-03，Asia/Shanghai**。这是当前工作区（含未提交源码）的精简开发快照，不是原 master 的分支或历史重写，也不是完整硬件交付包。

- 原目录：`C:\Users\zzh\OneDrive\Desktop\PCBBOM\嵌赛物联网`
- 原 master 提交：`b7bb90370f444b55e4e482c8d0f6e671bfeef5a1`。原提交、索引、远程和工作区源码未改。
- 独立快照目录：`C:\Users\zzh\OneDrive\Desktop\AIC\AmazingHand_Core_2026-10-03`
- 目标：<https://github.com/asungod/amazinghand>，保持私人；新远程名`amazinghand`，新历史分支`main`。不复用或覆盖`origin`，不推原 master，不强推。

## 1. 纳入与排除

纳入`smart_hand`内的MaixCAM2源码、Titan C源码/头文件、宿主工具、测试源码及stub头文件、小型配置/测试向量/空白模板、训练脚本和现有生成模型C数组、必要开发/安全/历史验证文档；根目录只有这份RESUME。`opensignhand_release`仅为说明、来源和许可材料，不是最新部署包。

完整排除根`outputs`、`tmp`、其他比赛目录及素材；`smart_hand/outputs`、`smart_hand/smart_hand`的嵌套产物、`competition_2026`、`.serena`、`third_party`虚拟环境；排除`node_modules`、缓存、EXE、编译/烧录产物、压缩包、PDF/DOCX、图片/视频、`.env`、密钥/令牌和原始参与者采样/数据集。没有`.git`旧历史、TFLite/AXModel权重或完整厂商BSP。

为保持测试可继续运行，进行了**仅本快照**的代码归位：

- 原`outputs/OpenSignHand_Capture_Kit_2026-10-01`的4个Python源码归到`smart_hand/capture_kit`；只带启动器、采集器、分类器和特征函数，不带照片/JSONL。采集器`CONSENT=False`，原参与者授权不随快照转移。
- 原`outputs/OpenSignHand_Device_Gesture_Review_2026-10-03/analyze_capture.py`归到`smart_hand/host/analyze_capture.py`。
- 原`tools/voice_memory_budget.py`归到`smart_hand/host/voice_memory_budget.py`，调整根目录定位。
- 修正相关4个测试文件的上述引用路径；新增离线核心测试入口`smart_hand/host/run_core_tests.py`。
- 本轮表达情境交付说明归到`smart_hand/docs/ACCESSIBLE_CONTEXT_2026-10-03.md`，不带截图。

保留的老文档可能引用本快照未带入的outputs、旧部署、绝对设备路径或8月状态。**从本文件了解当前状态，不把历史记录当最新硬件现状。** 私人可读也不代表可以公开再分发；公开发布前仍需核对第三方代码、模型及内容权利。

## 2. 如何运行已有测试

在含`smart_hand`的本快照/克隆根目录运行。已验证环境：Python 3.11.7、Node.js 24.13.0；部分C测试使用MinGW GCC 8.1.0。Node.js用于执行真实网页脚本，不需要node_modules。核心测试不需要API Key、设备、串口、Maix SDK或舵机电源。

```powershell
# 在你的克隆目录打开终端；此路径是本机独立快照目录
Set-Location -LiteralPath 'C:\Users\zzh\OneDrive\Desktop\AIC\AmazingHand_Core_2026-10-03'
python -B -X utf8 smart_hand/host/run_core_tests.py
python -B -X utf8 smart_hand/host/check_maix_deploy.py
```

本次独立快照核心套件**264项通过**；部署预检通过。覆盖协议、Maix主循环、课程/动态序列、网页真实JS、AI代理离线替身、文字卡隐私和采集/同帧分析。不能据此宣称真机准确率、完整手语或用户效果已经验收。

Windows本机HTTP替身测试在重复运行中曾发生一次连接中断（`test_http_rejects_wrong_origin_bad_data_missing_key_and_provider_failure`）；并非真实DeepSeek请求。保留这一环境不稳定记录，不以重试抹掉该现象。上面的264项通过指已成功完成的一次完整运行。

可选其他测试（应先检查依赖）：

```powershell
python -B -X utf8 -m unittest smart_hand.tests.test_voice_audio smart_hand.tests.test_voice_audio_titan smart_hand.tests.test_voice_app -q
python -B -X utf8 -m unittest smart_hand.tests.test_voice_memory_budget -q
python -B -X utf8 smart_hand/host/run_core_tests.py --full
```

- C宿主测试需要GCC；EXE是本地生成物，不能提交。
- 内存预算测试本机12项通过；部分只读测试还依赖本机RT-Thread Studio ARM工具链、`D:/Micu/RTTWorkspace/titan_uart_test`的ELF/MAP/链接脚本，均未纳入快照。换电脑不能照抄成本地已验收。
- `test_drv_usart_v2.py`仍对外部驱动源码测试，可通过`DRV_USART_V2_C`/`DRV_USART_V2_H_DIR`指定；不是本快照自带完整BSP。
- 旧舵机工具依赖未纳入的`scservo_sdk`；应自行从合法来源配置其依赖，不复制原第三方虚拟环境。
- 部分训练/特征测试需要numpy、scikit-learn；TFLite对照需TensorFlow和被排除的模型文件。没有依赖时有skip，不能把skip计为通过。
- **全量旧套件不是全绿**：`test_rehab_imitation`的6个断言仍与当前简短屏幕文案不一致（质量文本/原因）；本次不修冻结的旧模块。最初直接从根discover运行715项，出现8失败/9错误/6跳过，包含旧host导入布局、未纳入SDK及当时未归位的内存工具；后两类路径在核心入口/工具归位中处理，不能把初次计数当最终全量通过。`--full`用于重现剩余问题，不是默认验收绿灯。

不要以`host/run_all_checks.ps1`作为当前全量已通过的证据。不要为使测试绿而删断言、制造设备数据或绕过安全门控。

## 3. 当前已做成什么

- 静态V/L规则修复；用户曾报告实际静态手型识别改善，不能推广为整段准确率。
- 六类连续动作二维序列原型，分步提示、保持判定和短暂漏检暂停；没有专业手语语义/身体位置/表情认证。
- 分级课程、明确下一项提示、课程通过记录与实时识别分开、实时结果过期撤销显示；字幕一次性映射避免V/L被其他短令牌覆盖。
- 过程记录与报告、浏览器可选匿名训练历史；网页轮询不是独立视频帧或做错次数。
- DeepSeek兼容本地代理与手动网页请求；用户提供过建议生成结果。本快照验证仅为离线替身，未读取密钥或再次收费调用。
- 13课表达情境、手动文字沟通卡、大字/增强对比。卡片不进入历史、报告、AI摘要或机械动作；未做残障用户可用性验证。

## 4. 哪些代码保持冻结

未经明确任务与安全验收，不改：

- `smart_hand/titan_rtthread`的机械配方/位置常量/软限位、ACK/CRC/序号/故障恢复/通信门控；模型C数组、量化和协议合同。源码保存不等于准许烧录或上电。
- `voice_app_titan.h`的`VOICE_APP_ENABLE=0`默认关闭；不把语音/AI分析接到动作，不恢复PDM集成实验。
- `maixcam2/gesture_classifier.py`和`gesture_features.py`当前静态规则，不为解决一个样本盲改全局阈值。更改需独立任务、失败样本和对照回归。
- AI代理冻结成功响应：`{"advice":"…","source":"model|local","fallback_reason":null或白名单原因}`。模型来源必须reason=null；本地来源必须合法原因；密钥错误只返回error。词法事实检查有边界，不是完整自然语言事实保证。
- 人工确认训练、识别不直接触发动作、原始照片/关键点不上云、AI文字不改变课程判定。不猜测当前设备供电与固件状态。

冻结分类器SHA-256：`1A18436AD1E5D2466043E4B3121C7337BD2141EF7DBD4C151CADEA5633C79A2A`。
冻结特征SHA-256：`ADDF7FC1CEB04ADB8C493F67924661B4CF15DA21518764ED9F4F91B9B8AB2ADF`。
本次网页SHA-256：`18C9D173F1C04C1DBFE7B9FB8626BBEAEEC0641B0D57E85DAF8C576F8E4EE117`。

## 5. 哪些功能还没做完，下次从哪里接着改

1. **AI来源标识**：`maixcam2/web_stream.py`目前还只消费advice，需严格接入source/fallback_reason，区分模型原文和本地回退，保存到下载报告。代理`ai_course_advice_proxy.py`合同不要再随意扩字段。测试：`test_ai_course_advice_proxy.py`、`test_course_report_quality.py`、`test_web_stream.py`。
2. **复杂动作验收**：`maixcam2/sign_sequence.py`、`sign_lesson.py`、`rehab_hand_source.py`。用户曾高级0/6、求助卡第三步；已改短暂漏检/阶段时间边界，但不能说六个动作都真机稳定。先检查同帧几何、阶段原因和实际运行版本，不能把矛盾标签当用户动作错误。测试：`test_sign_sequence.py`、`test_sign_integration.py`。
3. **沟通需求与教学内容**：`web_stream.py`中的EXPRESSION_CONTEXT/updateMeaning/文字卡；参考`docs/ACCESSIBLE_CONTEXT_2026-10-03.md`与`test_accessible_context.py`。获得知情反馈、授权示范与专业核验前，不把原型说成标准手语或康复疗效。
4. **现场图像/状态时序核对**：`maixcam2/main.py`、`rehab_hand_source.py`、`web_stream.py`。课程终态与实时识别已分离，实际握拳却显示张掌的原因仍需同帧证据，不靠截图猜阈值。
5. **旧回归/移植依赖整理**：`rehab_imitation.py`及其测试、外部SDK和固件工具链路径；保持事实记录，按独立任务处理，不借快照导出改变行为。

## 6. 硬件运行与凭据边界

Maix入口是完整`smart_hand/maixcam2`工程，不是单独main.py。AXModel等设备模型及enable开关文件不在这个源码快照里；应在现场按授权运行手册准备，不能假设克隆即能直接部署。现有本机候选目录仍留在原项目outputs，本快照不替代它。仅查看讲解和文字卡不需要机械手6V上电。

需分析时，在电脑的交互终端使用代理`--prompt-key`隐藏输入或已有环境变量；不要在源码、配置、网页或日志中写密钥。Git使用Windows现有asungod登录；不要新建令牌或读取/输出凭据。无密钥也能跑核心离线测试和规则报告。

本次只上传私人代码快照。没有固件烧录、设备连接、供电操作、原始人像上传或收费API调用。以后公开前重新做许可证/隐私与比赛匿名化检查。
