"""39/41/65 supported-class mock VISION injector (test-only, no servo).

Purpose
-------
Drive the Titan pose-layer rejection test defined by
``docs/NEXT_SUPPORTED_CLASS_MOCK_TEST_PLAN_2026-08-14.md`` without editing any
production file.  One unchanged copy of this script covers class 39, 41 and 65;
the class is chosen at run time, never by editing source.

Safety model
------------
* Importing this module does nothing: no serial, no ``maix`` import, no file
  writes.  All behaviour lives behind ``main()``.
* Default mode is ``dry_run`` everywhere.  Live sending needs a positively
  identified MaixCAM2 (``maix.sys.device_id() == "maixcam2"``) plus three
  explicit tokens, one of which must be re-stated for every class change.
  Anything missing, unexpected or raising keeps the run in ``dry_run`` and the
  UART untouched: no pinmap configuration, no port open, no byte written.
* A live run stops at the first sign of trouble and reports ``ABORTED``.  It can
  only report ``PASS`` when nothing went wrong at all.
* Frame encoding and ACK accounting are imported from the production
  ``protocol`` / ``link_monitor`` modules.  Nothing is reimplemented here.
* No servo capability of any kind.  This script never writes any file.

Class selection (see the usage note in ``docs/``)
-------------------------------------------------
Priority: command line > environment variable > selection file.
On MaixVision the selection file is the intended path: create
``supported_class_mock_probe_selection.txt`` next to this script containing a
single line ``39``, ``41`` or ``65``.  That file is plain data, not source, so
this script's own bytes stay identical across all three rounds.
"""

import json
import os
import sys

from link_monitor import AckMonitor, write_tracked
from protocol import StreamParser, encode_frame


PROBE_NAME = "supported_class_mock_probe"

# Plan §2.2 constraint 3: exactly these three classes, nothing else.
ALLOWED_CLASS_IDS = (39, 41, 65)
CLASS_ACTION_NAMES = {
    39: "CYLINDRICAL_GRASP",
    41: "POWER_GRASP",
    65: "PRECISION_GRASP",
}

# Plan §2.2 constraints 4 and 5: frozen payload tail, confidence pinned at 96.
FIXED_CENTER_X = 320
FIXED_CENTER_Y = 240
FIXED_WIDTH = 80
FIXED_HEIGHT = 120
FIXED_CONFIDENCE = 96

SELECTION_FILENAME = "supported_class_mock_probe_selection.txt"
CLASS_ENV_NAME = "SUPPORTED_CLASS_MOCK_CLASS"

# Live sending requires all three tokens, exactly.  None of them has a default.
LIVE_ENABLE_TOKEN = "ENABLE"
LIVE_ACK_TOKEN = "SERVO_DISCONNECTED_NO_5V"
EXPECTED_DEVICE_ID = "maixcam2"

UART_DEVICE = "/dev/ttyS2"
UART_BAUD = 115200
TX_PIN = "B0"
TX_FUNC = "UART2_TX"
RX_PIN = "B1"
RX_FUNC = "UART2_RX"

RUN_SECONDS = 10
PING_INTERVAL_MS = 1000
VISION_INTERVAL_MS = 500
ACK_TIMEOUT_MS = 1000
STATS_INTERVAL_MS = 5000
LOOP_SLEEP_MS = 10

OUTCOME_PASS = "PASS"
OUTCOME_ABORTED = "ABORTED"
OUTCOME_DRY_RUN = "DRY_RUN"

_ASCII_DIGITS = "0123456789"


class SelectionError(ValueError):
    """Raised when the requested class or live authorisation is not valid."""


def coerce_class_id(raw):
    """Return one of ALLOWED_CLASS_IDS or raise SelectionError.

    Rejects missing values, booleans, floats, non-ASCII digits, signed text,
    and every class outside the allow-list.  There is no fallback default and
    no truncation or modulo of any kind.
    """
    if raw is None:
        raise SelectionError(
            "no class selected; choose one of {}".format(list(ALLOWED_CLASS_IDS))
        )
    if isinstance(raw, bool):
        raise SelectionError("class must be an integer, not a boolean")
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise SelectionError("class is empty")
        for character in text:
            if character not in _ASCII_DIGITS:
                raise SelectionError(
                    "class must be plain ASCII digits, got {!r}".format(raw)
                )
        value = int(text)
    else:
        raise SelectionError(
            "class must be an integer or digit string, got {}".format(type(raw).__name__)
        )
    if value not in ALLOWED_CLASS_IDS:
        raise SelectionError(
            "class {} is not allowed; only {} are authorised by the test plan".format(
                value, list(ALLOWED_CLASS_IDS)
            )
        )
    return value


def build_payload(class_id):
    """Return the six-field VISION payload for an allowed class.

    The five trailing fields are module constants and cannot be overridden by
    any caller: this function takes no other argument on purpose.
    """
    return (
        coerce_class_id(class_id),
        FIXED_CENTER_X,
        FIXED_CENTER_Y,
        FIXED_WIDTH,
        FIXED_HEIGHT,
        FIXED_CONFIDENCE,
    )


def parse_selection_text(text):
    """Parse the operator selection file into a plain dict.

    Accepted forms::

        39
        class=39
        live=ENABLE
        live_ack=SERVO_DISCONNECTED_NO_5V
        live_class=39

    Blank lines and ``#`` comments are ignored.  Duplicate keys are an error so
    that an edited file can never be ambiguous.
    """
    selection = {}
    if text is None:
        return selection
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            key, _, value = stripped.partition("=")
            key = key.strip().lower()
            value = value.strip()
        else:
            key = "class"
            value = stripped
        if key not in ("class", "live", "live_ack", "live_class"):
            raise SelectionError(
                "line {}: unknown key {!r} in selection file".format(number, key)
            )
        if key in selection:
            raise SelectionError(
                "line {}: duplicate key {!r} in selection file".format(number, key)
            )
        selection[key] = value
    return selection


def selection_file_path(script_path=None):
    base = script_path if script_path is not None else __file__
    return os.path.join(os.path.dirname(os.path.abspath(base)), SELECTION_FILENAME)


def read_selection_file(path=None):
    """Read the selection file if present.  Returns (text, source) or (None, None).

    Opened read-only.  A missing file is not an error here; it becomes a
    SelectionError later only if no class was supplied by any other source.
    """
    target = path if path is not None else selection_file_path()
    try:
        handle = open(target, "r")
    except (IOError, OSError):
        return None, None
    try:
        return handle.read(), target
    finally:
        handle.close()


def parse_arguments(argv):
    """Minimal argument parsing.  No defaults for any live token."""
    parsed = {
        "class": None,
        "live": None,
        "live_ack": None,
        "live_class": None,
        "help": False,
    }
    index = 0
    while index < len(argv):
        item = argv[index]
        if item in ("-h", "--help"):
            parsed["help"] = True
        elif item == "--class":
            index += 1
            if index >= len(argv):
                raise SelectionError("--class needs a value")
            parsed["class"] = argv[index]
        elif item.startswith("--class="):
            parsed["class"] = item.split("=", 1)[1]
        elif item == "--live":
            parsed["live"] = LIVE_ENABLE_TOKEN
        elif item == "--live-ack":
            index += 1
            if index >= len(argv):
                raise SelectionError("--live-ack needs a value")
            parsed["live_ack"] = argv[index]
        elif item.startswith("--live-ack="):
            parsed["live_ack"] = item.split("=", 1)[1]
        elif item == "--live-class":
            index += 1
            if index >= len(argv):
                raise SelectionError("--live-class needs a value")
            parsed["live_class"] = argv[index]
        elif item.startswith("--live-class="):
            parsed["live_class"] = item.split("=", 1)[1]
        else:
            raise SelectionError("unknown argument {!r}".format(item))
        index += 1
    return parsed


def detect_device_identity():
    """Positively identify a MaixCAM2.  Returns (is_maixcam2, detail).

    Importing ``maix.sys`` and reading ``device_id()`` touches no UART, no pin
    and no camera.  Every failure mode - module absent, attribute missing, call
    raising, unexpected identifier - returns False so the caller stays dry.
    """
    try:
        from maix import sys as maix_sys
    except ImportError:
        return False, "maix runtime absent (not a MaixCAM2 host)"
    except Exception as exc:  # noqa: BLE001 - any import failure must stay dry
        return False, "importing maix.sys failed: {}".format(exc)

    device_id_fn = getattr(maix_sys, "device_id", None)
    if not callable(device_id_fn):
        return False, "maix.sys.device_id is unavailable on this runtime"
    try:
        device_id = device_id_fn()
    except Exception as exc:  # noqa: BLE001 - a raising probe must stay dry
        return False, "maix.sys.device_id() raised: {}".format(exc)

    if device_id != EXPECTED_DEVICE_ID:
        return False, "device_id is {!r}, expected {!r}".format(
            device_id, EXPECTED_DEVICE_ID
        )
    return True, "device_id={!r}".format(EXPECTED_DEVICE_ID)


class Request(object):
    def __init__(self, class_id, live, class_source, live_refused_reason, device_detail):
        self.class_id = class_id
        self.live = live
        self.class_source = class_source
        self.live_refused_reason = live_refused_reason
        self.device_detail = device_detail
        self.payload = build_payload(class_id)


def resolve_request(argv=None, environ=None, selection_text=None,
                    device_is_maixcam2=False, device_detail="not checked",
                    selection_source=None):
    """Resolve the class and the live authorisation.  Never defaults to live."""
    arguments = parse_arguments(list(argv or []))
    environ = {} if environ is None else environ
    selection = parse_selection_text(selection_text)

    raw_class = arguments["class"]
    source = "command line"
    if raw_class is None:
        raw_class = environ.get(CLASS_ENV_NAME)
        source = "environment variable {}".format(CLASS_ENV_NAME)
    if raw_class is None:
        raw_class = selection.get("class")
        source = "selection file {}".format(selection_source or SELECTION_FILENAME)
    if raw_class is None:
        raise SelectionError(
            "no class selected. Put a single line '39', '41' or '65' into {} "
            "next to this script, or pass --class 39 on a PC.".format(
                SELECTION_FILENAME
            )
        )
    class_id = coerce_class_id(raw_class)

    live_enable = arguments["live"] or selection.get("live")
    live_ack = arguments["live_ack"] or selection.get("live_ack")
    live_class = arguments["live_class"] or selection.get("live_class")

    live = False
    refused = None
    if live_enable is None and live_ack is None and live_class is None:
        refused = "no live authorisation supplied; dry run is the default"
    elif live_enable != LIVE_ENABLE_TOKEN:
        refused = "live enable token missing or wrong; expected {!r}".format(
            LIVE_ENABLE_TOKEN
        )
    elif live_ack != LIVE_ACK_TOKEN:
        refused = "live acknowledgement missing or wrong; expected {!r}".format(
            LIVE_ACK_TOKEN
        )
    elif live_class is None:
        refused = (
            "live_class missing; every round must restate live_class={} "
            "for the class it authorises".format(class_id)
        )
    else:
        try:
            confirmed_class = coerce_class_id(live_class)
        except SelectionError as exc:
            refused = "live_class rejected: {}".format(exc)
        else:
            if confirmed_class != class_id:
                refused = (
                    "stale authorisation: live_class={} does not match the "
                    "selected class {}; re-confirm live_class for this round".format(
                        confirmed_class, class_id
                    )
                )
            elif not device_is_maixcam2:
                refused = "device not identified as MaixCAM2 ({})".format(device_detail)
            else:
                live = True
    return Request(class_id, live, source, refused, device_detail)


def preview_frames(class_id):
    """Encode the frames that a live run would send, using the production codec."""
    payload = build_payload(class_id)
    return {
        "ping": encode_frame("PING", 0).decode("ascii").strip(),
        "vision": encode_frame("VISION", 1, *payload).decode("ascii").strip(),
    }


def error_counters(monitor, rx_errors):
    """The six counters that must all stay zero for a live PASS."""
    return (
        ("rx_errors", int(rx_errors)),
        ("tx_fail", int(monitor.send_failures)),
        ("malformed", int(monitor.malformed)),
        ("timeout", int(monitor.timed_out)),
        ("rejected", int(monitor.rejected)),
        ("unexpected", int(monitor.unexpected)),
    )


def first_nonzero_counter(counters):
    for name, value in counters:
        if value:
            return name, value
    return None


def build_report(request, mode, hardware_accessed, serial_opened,
                 outcome, abort_reason=None, extra=None):
    report = {
        "probe": PROBE_NAME,
        "mode": mode,
        "outcome": outcome,
        "abort_reason": abort_reason,
        "hardware_accessed": bool(hardware_accessed),
        "serial_opened": bool(serial_opened),
        "device_identity": request.device_detail,
        "class_id": request.class_id,
        "class_source": request.class_source,
        "expected_titan_action": CLASS_ACTION_NAMES[request.class_id],
        "expected_titan_pose": "NOT_CONFIGURED",
        "expected_titan_actionable": 0,
        "payload": list(request.payload),
        "device": UART_DEVICE,
        "baud": UART_BAUD,
        "servo_capability": False,
    }
    if request.live_refused_reason:
        report["live_refused_reason"] = request.live_refused_reason
    if extra:
        report.update(extra)
    return report


def run_dry(request):
    """PC / unauthorised path: print the frames only.  No port is touched."""
    return build_report(
        request,
        mode="dry_run",
        hardware_accessed=False,
        serial_opened=False,
        outcome=OUTCOME_DRY_RUN,
        abort_reason=None,
        extra={
            "frames_sent": 0,
            "rx_errors": 0,
            "link_stats": None,
            "frame_preview": preview_frames(request.class_id),
            "note": (
                "dry run: no serial enumeration, no serial open, no bytes written; "
                "DRY_RUN proves nothing about the link"
            ),
        },
    )


def elapsed_ms(now_ms, previous_ms, ticks_diff=None):
    if ticks_diff is not None:
        # MaixPy argument order is (previous, current), unlike MicroPython.
        return ticks_diff(previous_ms, now_ms)
    return now_ms - previous_ms


def run_live_with_serial(request, serial, now_ms_fn, sleep_ms_fn,
                         ticks_diff=None, run_seconds=RUN_SECONDS, printer=print):
    """Authorised send loop with injected I/O so it can be exercised offline.

    Stops at the first failure of any kind and reports ABORTED.  Ordering
    contract per round: read, process ACKs, then the pre-send safety gate
    (expire + counter sweep), and only then any write_tracked call.  A frame
    that has already timed out therefore cannot buy one more round of traffic.
    Uses the production AckMonitor / write_tracked / StreamParser: this module
    keeps no statistics of its own and never encodes a frame by hand.
    """
    monitor = AckMonitor(ACK_TIMEOUT_MS)
    parser = StreamParser()
    sequence = 0
    start_ms = now_ms_fn()
    last_ping_ms = None
    last_vision_ms = None
    last_stats_ms = None
    vision_sent = 0
    ping_sent = 0
    rx_errors = 0
    abort_reason = None

    def diff(now_value, previous_value):
        return elapsed_ms(now_value, previous_value, ticks_diff)

    def sweep_counters():
        problem = first_nonzero_counter(error_counters(monitor, rx_errors))
        if problem is None:
            return None
        return "error counter {} reached {}".format(problem[0], problem[1])

    while abort_reason is None:
        now_ms = now_ms_fn()
        if diff(now_ms, start_ms) >= run_seconds * 1000:
            break

        try:
            received = serial.read()
        except Exception as exc:  # noqa: BLE001 - a read fault must abort the run
            rx_errors += 1
            abort_reason = "serial.read raised: {}".format(exc)
            break

        if received:
            now_ms = now_ms_fn()
            for message in parser.feed(received):
                if message["type"] != "ACK":
                    printer("Titan message: {}".format(message))
                    continue
                if len(message["args"]) != 1:
                    monitor.note_malformed()
                    abort_reason = "malformed ACK: {}".format(message)
                    break
                result = monitor.acknowledge(
                    message["seq"],
                    message["args"][0],
                    now_ms,
                    lambda a, b: diff(a, b),
                )
                if result != "acked":
                    abort_reason = "ACK result {} for seq={}".format(
                        result, message["seq"]
                    )
                    break
            if abort_reason is not None:
                break

        # Pre-send safety gate.  Nothing may be transmitted while a previously
        # sent frame has already reached the ACK timeout, or while any error
        # counter is non-zero.  This runs before every write_tracked call so a
        # fault can never buy itself one more round of traffic.
        expired = monitor.expire(now_ms, lambda a, b: diff(a, b))
        if expired:
            abort_reason = "ACK timeout for {}".format(
                ", ".join("seq={} {}".format(seq, kind) for seq, kind in expired)
            )
            break

        abort_reason = sweep_counters()
        if abort_reason is not None:
            break

        if last_ping_ms is None or diff(now_ms, last_ping_ms) >= PING_INTERVAL_MS:
            frame = encode_frame("PING", sequence)
            success, error_text = write_tracked(
                serial, frame, sequence, "PING", now_ms, monitor
            )
            if not success:
                abort_reason = "PING write failed at seq={}: {}".format(
                    sequence, error_text
                )
                break
            ping_sent += 1
            sequence = (sequence + 1) & 0xFFFF
            last_ping_ms = now_ms

        if last_vision_ms is None or diff(now_ms, last_vision_ms) >= VISION_INTERVAL_MS:
            frame = encode_frame("VISION", sequence, *request.payload)
            success, error_text = write_tracked(
                serial, frame, sequence, "VISION", now_ms, monitor
            )
            if not success:
                abort_reason = "VISION write failed at seq={}: {}".format(
                    sequence, error_text
                )
                break
            vision_sent += 1
            sequence = (sequence + 1) & 0xFFFF
            last_vision_ms = now_ms

        # Post-send check: a write that reported success must still not have
        # moved any error counter.  This does not replace the gate above.
        abort_reason = sweep_counters()
        if abort_reason is not None:
            break

        if last_stats_ms is None or diff(now_ms, last_stats_ms) >= STATS_INTERVAL_MS:
            printer("link stats: {}".format(monitor.summary()))
            printer("uart stats: rx_errors={}".format(rx_errors))
            last_stats_ms = now_ms

        sleep_ms_fn(LOOP_SLEEP_MS)

    if abort_reason is None:
        abort_reason = sweep_counters()
    frames_sent = ping_sent + vision_sent
    backlog = monitor.sent - monitor.acked
    if abort_reason is None:
        if frames_sent == 0:
            abort_reason = "no frame was sent; nothing was proved"
        elif backlog > 1:
            abort_reason = "acknowledgement backlog: sent={} acked={}".format(
                monitor.sent, monitor.acked
            )

    outcome = OUTCOME_PASS if abort_reason is None else OUTCOME_ABORTED
    printer("link stats: {}".format(monitor.summary()))
    printer("uart stats: rx_errors={}".format(rx_errors))
    printer("outcome: {}".format(outcome))
    if abort_reason is not None:
        printer("abort_reason: {}".format(abort_reason))

    return build_report(
        request,
        mode="live",
        hardware_accessed=True,
        serial_opened=True,
        outcome=outcome,
        abort_reason=abort_reason,
        extra={
            "frames_sent": frames_sent,
            "vision_sent": vision_sent,
            "ping_sent": ping_sent,
            "rx_errors": rx_errors,
            "sent": monitor.sent,
            "acked": monitor.acked,
            "backlog": backlog,
            "error_counters": dict(error_counters(monitor, rx_errors)),
            "link_stats": monitor.summary(),
            "run_seconds": run_seconds,
            "note": (
                "stop the script, wait for Titan 'sequence baseline reset', "
                "then run standard main.py to return to class=3"
            ),
        },
    )


def run_on_maix(request):
    """Only reachable after detect_device_identity() confirmed a MaixCAM2."""
    from maix import err, pinmap, time, uart

    err.check_raise(
        pinmap.set_pin_function(TX_PIN, TX_FUNC),
        "failed to configure {} as {}".format(TX_PIN, TX_FUNC),
    )
    err.check_raise(
        pinmap.set_pin_function(RX_PIN, RX_FUNC),
        "failed to configure {} as {}".format(RX_PIN, RX_FUNC),
    )
    serial = uart.UART(UART_DEVICE, UART_BAUD)
    return run_live_with_serial(
        request,
        serial,
        now_ms_fn=time.ticks_ms,
        sleep_ms_fn=time.sleep_ms,
        ticks_diff=getattr(time, "ticks_diff", None),
    )


USAGE = """\
supported_class_mock_probe - inject one supported class (39/41/65) as mock VISION.

MaixVision (no command line):
  1. create {selection} next to this script
  2. put a single line in it: 39, 41 or 65
  3. run this script; it prints a dry run by default
  4. to send for real, add these three lines to the same file:
       live={enable}
       live_ack={ack}
       live_class=<the same class as line 1>
  5. every round: change BOTH the class line AND live_class, or the run
     falls back to dry run and sends nothing

PC:
  python supported_class_mock_probe.py --class 39
  A PC is never identified as {device}, so it always stays in dry run:
  no port is enumerated, opened or written.
""".format(
    selection=SELECTION_FILENAME,
    enable=LIVE_ENABLE_TOKEN,
    ack=LIVE_ACK_TOKEN,
    device=EXPECTED_DEVICE_ID,
)


def main(argv=None, environ=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    environ = os.environ if environ is None else environ
    try:
        arguments = parse_arguments(argv)
    except SelectionError as exc:
        print("selection refused: {}".format(exc))
        print(USAGE)
        return 2
    if arguments["help"]:
        print(USAGE)
        return 0

    selection_text, selection_source = read_selection_file()
    device_is_maixcam2, device_detail = detect_device_identity()
    try:
        request = resolve_request(
            argv=argv,
            environ=environ,
            selection_text=selection_text,
            device_is_maixcam2=device_is_maixcam2,
            device_detail=device_detail,
            selection_source=selection_source,
        )
    except SelectionError as exc:
        print("selection refused: {}".format(exc))
        print("no frame was encoded and no serial device was touched.")
        print(USAGE)
        return 2

    if request.live:
        report = run_on_maix(request)
    else:
        report = run_dry(request)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["outcome"] == OUTCOME_ABORTED:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
