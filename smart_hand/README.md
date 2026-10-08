# 知手同行应用与控制代码

系统由 MaixCAM2 视觉节点、Titan 控制节点、AmazingHand 机械手及浏览器页面组成。

| 目录 | 用途 |
| --- | --- |
| `maixcam2` | 视觉采集、手型规则、课程步骤与网页接口 |
| `titan_rtthread` | UART 通信、动作配方与执行状态 |
| `host` | 离线预览、配置预检及主机工具 |
| `tests` | Python、JavaScript 与 C 主机测试 |
| `protocol` | 跨节点消息格式 |
| `docs`、`validation_reports` | 开发记录与验证文档 |

从仓库根目录运行 `python -B -X utf8 smart_hand/host/offline_demo.py` 预览界面，运行 `python -B -X utf8 smart_hand/host/run_core_tests.py` 执行教学核心测试。

项目介绍、实物照片和正式材料见[仓库首页](../README.md)，设备配置见[部署说明](../docs/DEPLOYMENT.md)。
