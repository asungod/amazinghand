# 核心测试

在仓库根目录安装 Python 3.11+ 和 Node.js 后运行：

```bash
python -B -X utf8 smart_hand/host/run_core_tests.py
python -B -X utf8 smart_hand/host/check_maix_deploy.py --expected-mode yolo11
```

`run_core_tests.py` 显式列出教学应用套件。Python 测试验证课程与设备适配，Node.js 执行页面脚本测试，HTTP 测试使用本机接口，设备与模型使用测试替身。

| 测试范围 | 主要内容 |
| --- | --- |
| 课程与步骤 | 保持时间、顺序推进、短暂漏检、进度保存 |
| 网页交互 | 课程选择、步骤提示、文字卡、报告下载 |
| 人工复核 | 结果独立记录、会话对应、页面与报告展示 |
| 建议服务 | 摘要核对、来源标记、服务响应与本地规则建议 |
| 视觉与通信 | 当前帧重试、错误处理、UART 消息与状态时效 |

测试执行摘要见 [validation/core-tests.txt](validation/core-tests.txt)，配置预检输出见 [validation/deploy-check.txt](validation/deploy-check.txt)。实机练习和主机验证分别记录，实物及界面结果见[运行佐证](submission/resources-and-validation.pdf)。

设备驱动、语音、训练工具等其他套件位于 `smart_hand/tests`，按各自依赖运行。核心入口保持固定模块列表，便于在普通主机复现教学应用。
