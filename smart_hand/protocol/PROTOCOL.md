# Smart Hand UART Protocol v0.1

## 设计目标

- 初期可用串口助手直接阅读。
- 能处理 UART 分包、粘包和行首垃圾。
- 用序号发现丢包和重复包。
- 用 CRC16 拒绝损坏帧。
- 单帧不超过 128 字节。

## 帧格式

```text
$TYPE,SEQ[,ARG0,ARG1...]*CCCC\r\n
```

- `$`：帧头。
- `TYPE`：大写消息类型。
- `SEQ`：0-65535，发送方递增，溢出后回到 0。
- `ARGn`：十进制无符号整数。
- `*`：正文结束。
- `CCCC`：4 位大写十六进制 CRC16-CCITT。
- CRC 范围：`$` 后至 `*` 前的全部 ASCII 字节。

示例中的 CRC 仅以实际程序计算值为准：

```text
$PING,1*CCCC\r\n
$ACK,1,0*CCCC\r\n
$VISION,2,3,320,240,80,120,96*CCCC\r\n
```

## 消息

### PING

```text
$PING,SEQ*CRC
```

MaixCAM2 每秒发送一次。Titan 用其维护视觉链路心跳。

### ACK

```text
$ACK,SEQ,STATUS*CRC
```

- `SEQ`：被确认帧的序号。
- `STATUS=0`：成功。
- 其他值保留为错误码。

### VISION

```text
$VISION,SEQ,CLASS_ID,CX,CY,W,H,CONFIDENCE*CRC
```

- `CLASS_ID`：物体类别 ID。
- `CX/CY`：检测框中心像素坐标。
- `W/H`：检测框宽高。
- `CONFIDENCE`：0-100。

### STATUS

```text
$STATUS,SEQ,STATE,ERROR*CRC
```

状态预留：

- `0`：BOOT。
- `1`：READY。
- `2`：TARGET_VALID。
- `3`：VISION_OFFLINE。
- `4`：FAULT。

## 超时与安全

- Titan 收到有效 `PING` 或 `VISION` 时更新最后通信时间。
- 1500ms 内没有有效帧则进入 `VISION_OFFLINE`。
- CRC 错误、字段越界、未知类型不能刷新心跳。
- 后续接入机械手后，`VISION_OFFLINE` 不得触发新的抓取动作。

