"""Smart Hand UART protocol shared by MaixCAM2 and host tests."""

MAX_FRAME_SIZE = 128
MAX_ARGS = 8
MAX_UINT16 = 0xFFFF
MAX_UINT32 = 0xFFFFFFFF
MESSAGE_TYPES = (
    "PING",
    "ACK",
    "VISION",
    "STATUS",
    "TRAIN",
    "TRAINSTAT",
    "SIGN",
    "SIGNSTAT",
    "AITRUST",
)


def crc16_ccitt(data, initial=0xFFFF):
    crc = initial
    for value in data:
        crc ^= value << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def _unsigned_decimal(value, maximum, field_name):
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("{} must be an integer".format(field_name)) from exc
    if isinstance(value, float) and value != parsed:
        raise ValueError("{} must be an integer".format(field_name))
    if parsed < 0 or parsed > maximum:
        raise ValueError("{} out of range".format(field_name))
    return parsed


def encode_frame(message_type, sequence, *args):
    message_type = str(message_type).upper()
    if message_type not in MESSAGE_TYPES:
        raise ValueError("unknown message type")
    if len(args) > MAX_ARGS:
        raise ValueError("too many arguments")
    sequence = _unsigned_decimal(sequence, MAX_UINT16, "sequence")
    encoded_args = [
        _unsigned_decimal(value, MAX_UINT32, "argument") for value in args
    ]
    fields = [message_type, str(sequence)]
    fields.extend(str(value) for value in encoded_args)
    body = ",".join(fields).encode("ascii")
    checksum = crc16_ccitt(body)
    frame = b"$" + body + b"*%04X\r\n" % checksum
    if len(frame) > MAX_FRAME_SIZE:
        raise ValueError("frame exceeds maximum size")
    return frame


def decode_frame(frame):
    if isinstance(frame, str):
        frame = frame.encode("ascii")
    frame = frame.strip()
    if len(frame) < 9 or len(frame) > MAX_FRAME_SIZE:
        raise ValueError("invalid frame length")
    if not frame.startswith(b"$"):
        raise ValueError("missing frame header")
    separator = frame.rfind(b"*")
    if separator < 2 or len(frame) - separator != 5:
        raise ValueError("invalid frame trailer")

    body = frame[1:separator]
    crc_text = frame[separator + 1 :]
    if any(value not in b"0123456789ABCDEFabcdef" for value in crc_text):
        raise ValueError("invalid CRC text")
    expected_crc = int(crc_text, 16)
    actual_crc = crc16_ccitt(body)
    if actual_crc != expected_crc:
        raise ValueError("CRC mismatch")

    parts = body.decode("ascii").split(",")
    if len(parts) < 2 or not parts[0]:
        raise ValueError("missing message fields")
    if parts[0] not in MESSAGE_TYPES:
        raise ValueError("unknown message type")
    if len(parts) - 2 > MAX_ARGS:
        raise ValueError("too many arguments")
    try:
        sequence = int(parts[1])
        args = [int(value) for value in parts[2:]]
    except ValueError as exc:
        raise ValueError("non-integer field") from exc
    if sequence < 0 or sequence > MAX_UINT16:
        raise ValueError("sequence out of range")
    if any(value < 0 or value > MAX_UINT32 for value in args):
        raise ValueError("argument out of range")
    return {"type": parts[0], "seq": sequence, "args": args}


class StreamParser:
    def __init__(self):
        self._buffer = bytearray()

    def feed(self, data):
        if data:
            self._buffer.extend(data)
        frames = []

        while True:
            start = self._buffer.find(b"$")
            if start < 0:
                if len(self._buffer) > MAX_FRAME_SIZE:
                    self._buffer.clear()
                break
            if start:
                del self._buffer[:start]

            newline = self._buffer.find(b"\n")
            restart = self._buffer.find(b"$", 1)
            if restart >= 0 and (newline < 0 or restart < newline):
                del self._buffer[:restart]
                continue
            if newline < 0:
                if len(self._buffer) > MAX_FRAME_SIZE:
                    self._buffer.clear()
                break

            candidate = bytes(self._buffer[: newline + 1])
            del self._buffer[: newline + 1]
            try:
                frames.append(decode_frame(candidate))
            except ValueError:
                continue

        return frames
