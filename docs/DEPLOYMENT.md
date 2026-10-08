# 运行与设备配置

## 离线预览

Python 3.11+ 即可运行 `smart_hand/host/offline_demo.py`，默认地址为 `http://127.0.0.1:8880/`。课程目录和步骤说明由应用源码生成，报告使用内置示例。可通过 `--port` 指定端口。

## MaixCAM2 视觉节点

使用 MaixVision 打开 `smart_hand/maixcam2`，以多文件项目方式运行 `main.py`。手部关键点调用 Sipeed `nn.HandLandmarks`，模型路径为：

```text
/root/models/hand_landmarks.mud
```

模型与设备运行环境从 Sipeed 官方渠道配置。[手部关键点接口文档](https://wiki.sipeed.com/maixpy/doc/zh/vision/hand_landmarks.html)要求 MaixPy 固件 4.9.3 或更新版本。

课程模式由环境变量 `SIGN_MODE=1` 或项目内的空文件 `opensignhand.enable` 开启。机械示范另由 `OPENSIGNHAND_MECHANICAL_DEMO=1` 或 `opensignhand_mechanical.enable` 开启。浏览器中的开始操作由用户确认。

主要配置位于 `main.py`：

| 配置 | 值或作用 |
| --- | --- |
| `HAND_MODEL_PATH` | 手部关键点模型路径 |
| `UART_DEVICE` | `/dev/ttyS2` |
| `UART_BAUD` | `115200` |
| `SIGN_MODE` | 课程模式 |
| `LIVE_WEB_ENABLED` | 浏览器预览与课程交互 |
| `SIGN_SESSION_LOG_PATH` | 课程记录文件 |

MaixCAM2 使用前面板 UART2 的 B0/B1；Titan 应用中的串口名称为 `uart2`。两节点通过 TX/RX 交叉及 GND 通信，各自使用对应供电。接线按板卡的实际丝印和官方手册核对。

运行前在主机执行配置预检：

```bash
python -B -X utf8 smart_hand/host/check_maix_deploy.py --expected-mode yolo11
```

该命令检查应用文件、导入及源码配置；手语模式由上述课程开关选择。

## Titan 控制节点

`smart_hand/titan_rtthread` 提供协议、UART 服务、执行状态与机械动作源码，接入对应 RT-Thread 工程编译。所用工程配置为 RT-Thread 5.1.0、Renesas FSP 6.4.0、GNU Arm 13.3。

协议定义见 `smart_hand/protocol`；课程请求与状态消息的应用处理见 `smart_hand/maixcam2/sign_motion.py` 和 `smart_hand/titan_rtthread/smart_hand_uart.c`。设备运行使用匹配的板级工程、引脚配置及机械标定参数。

## 练后建议服务

服务入口为 `smart_hand/ai_course_advice_proxy.py`，默认监听本机 8765 端口。先运行以下命令查看参数：

```bash
python smart_hand/ai_course_advice_proxy.py --help
```

启动时用 `--origin` 指定设备学习页面的完整来源地址，用 `--prompt-key` 交互输入 API 密钥。默认服务为 `https://api.deepseek.com`，模型配置为 `deepseek-flash`；可通过 `OPEN_SIGN_AI_BASE_URL` 和 `OPEN_SIGN_AI_MODEL` 替换。

页面显示建议来源与处理说明。本项目实机材料展示本地规则建议，课程结果与机械示范由课程和控制模块独立处理。
