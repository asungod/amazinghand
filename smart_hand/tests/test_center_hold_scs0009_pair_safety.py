"""Behavioral safety contract for host/center_hold_scs0009_pair.py.

Offline only: PortHandler and scscl are replaced with in-process fakes.
No COM port is enumerated or opened. hardware_accessed must stay false.

These tests encode the Gate 2 pair-hold contract. A FAIL means the production
script does not yet enforce that rule. This batch does not patch the script;
failing tests are evidence for Codex, not a license to "fix forward" here.
"""

from __future__ import annotations

import builtins
import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "host"
SCRIPT = HOST / "center_hold_scs0009_pair.py"

COMM_SUCCESS = 0
COMM_TX_FAIL = -2
COMM_TX_ERROR = -4
COMM_RX_TIMEOUT = -6

SCSCL_MIN_ANGLE_LIMIT_L = 9
SCSCL_MAX_ANGLE_LIMIT_L = 11
SCSCL_TORQUE_ENABLE = 40
SCSCL_PRESENT_VOLTAGE = 62
SCSCL_PRESENT_TEMPERATURE = 63

EXPECTED_MODEL = 1284  # SCS0009-C001 ping model from 2026-08-15 bench
MAX_SAFE_SPEED = 100
ELECTRICAL_MIDPOINT = 511
HOLD_TOLERANCE = 8

HARDWARE_ACCESSED = False


def load_center_hold():
    spec = importlib.util.spec_from_file_location("center_hold_scs0009_pair", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += float(seconds)


class FakePort:
    instances: list["FakePort"] = []

    def __init__(self, name: str) -> None:
        global HARDWARE_ACCESSED
        if name.startswith("COM") or name.startswith("/dev/"):
            # The script may pass a COM name as a string; constructing this
            # fake is not hardware access. Opening a real serial device would be.
            pass
        self.name = name
        self.opened = False
        self.baud = None
        self.closed = False
        FakePort.instances.append(self)

    def openPort(self) -> bool:
        self.opened = True
        return True

    def setBaudRate(self, baud: int) -> bool:
        self.baud = baud
        return True

    def closePort(self) -> None:
        self.closed = True


@dataclass
class ServoState:
    online: bool = True
    model: int = EXPECTED_MODEL
    position: int = 400
    voltage: int = 60
    temperature: int = 24
    min_limit: int = 20
    max_limit: int = 1003
    torque: int = 0
    never_arrive: bool = False


@dataclass
class BusLog:
    pings: list[int] = field(default_factory=list)
    reads: list[tuple[int, str]] = field(default_factory=list)
    write_pos: list[tuple[int, int, int, int]] = field(default_factory=list)
    writes: list[tuple[int, int, int]] = field(default_factory=list)
    torque_off_attempts: list[int] = field(default_factory=list)
    torque_off_raises: list[int] = field(default_factory=list)


class FakePacket:
    last: "FakePacket | None" = None

    def __init__(self, port: FakePort) -> None:
        self.port = port
        self.servos = {
            1: ServoState(position=400),
            2: ServoState(position=600),
        }
        self.log = BusLog()
        self.goals_511: set[int] = set()
        self.arrived: set[int] = set()
        self.hold_cycles = 0
        self._hold_started = False
        self.fail_ping: set[int] = set()
        self.fail_enable: set[int] = set()
        self.fail_write_pos_phase: dict[int, str] = {}
        self.fail_read_pos: set[int] = set()
        self.short_write_ids: set[int] = set()
        self.raise_torque_off: set[int] = set()
        self.hold_hook = None
        self.write_pos_count: dict[int, int] = {1: 0, 2: 0}
        FakePacket.last = self

    def getTxRxResult(self, result: int) -> str:
        return f"comm={result}"

    def getRxPacketError(self, error: int) -> str:
        return f"err={error}"

    def ping(self, servo_id: int):
        self.log.pings.append(servo_id)
        servo = self.servos.get(servo_id)
        if servo_id in self.fail_ping or servo is None or not servo.online:
            return 0, COMM_RX_TIMEOUT, 0
        return servo.model, COMM_SUCCESS, 0

    def ReadPos(self, servo_id: int):
        self.log.reads.append((servo_id, "pos"))
        if servo_id in self.fail_read_pos:
            return 0, COMM_RX_TIMEOUT, 0
        servo = self.servos[servo_id]
        if self._hold_started and self.hold_hook is not None:
            self.hold_hook(self, "pre_hold_read", servo_id)
        position = servo.position
        if servo_id in self.goals_511 and abs(position - ELECTRICAL_MIDPOINT) <= HOLD_TOLERANCE:
            self.arrived.add(servo_id)
        return position, COMM_SUCCESS, 0

    def read1ByteTxRx(self, servo_id: int, address: int):
        servo = self.servos[servo_id]
        if address == SCSCL_PRESENT_VOLTAGE:
            self.log.reads.append((servo_id, "voltage"))
            if self.arrived >= {1, 2} and servo_id == 1:
                self._hold_started = True
                self.hold_cycles += 1
                if self.hold_hook is not None:
                    self.hold_hook(self, "hold_cycle", self.hold_cycles)
            return servo.voltage, COMM_SUCCESS, 0
        if address == SCSCL_PRESENT_TEMPERATURE:
            self.log.reads.append((servo_id, "temperature"))
            return servo.temperature, COMM_SUCCESS, 0
        if address == SCSCL_TORQUE_ENABLE:
            self.log.reads.append((servo_id, "torque"))
            return servo.torque, COMM_SUCCESS, 0
        return 0, COMM_TX_ERROR, 0

    def read2ByteTxRx(self, servo_id: int, address: int):
        servo = self.servos[servo_id]
        if address == SCSCL_MIN_ANGLE_LIMIT_L:
            self.log.reads.append((servo_id, "min_limit"))
            return servo.min_limit, COMM_SUCCESS, 0
        if address == SCSCL_MAX_ANGLE_LIMIT_L:
            self.log.reads.append((servo_id, "max_limit"))
            return servo.max_limit, COMM_SUCCESS, 0
        return 0, COMM_TX_ERROR, 0

    def WritePos(self, servo_id: int, position: int, time: int, speed: int):
        self.log.write_pos.append((servo_id, position, time, speed))
        self.write_pos_count[servo_id] = self.write_pos_count.get(servo_id, 0) + 1
        phase = "start" if self.write_pos_count[servo_id] == 1 else "reference"
        if self.fail_write_pos_phase.get(servo_id) == phase:
            return COMM_TX_FAIL, 0
        if servo_id in self.short_write_ids and phase == "reference":
            # Simulate a truncated goal write: SDK would surface TX_ERROR.
            return COMM_TX_ERROR, 0
        if position == ELECTRICAL_MIDPOINT:
            self.goals_511.add(servo_id)
            if not self.servos[servo_id].never_arrive:
                self.servos[servo_id].position = ELECTRICAL_MIDPOINT
        else:
            self.servos[servo_id].position = position
        return COMM_SUCCESS, 0

    def write1ByteTxRx(self, servo_id: int, address: int, value: int):
        self.log.writes.append((servo_id, address, value))
        if address == SCSCL_TORQUE_ENABLE and value == 0:
            self.log.torque_off_attempts.append(servo_id)
            if servo_id in self.raise_torque_off:
                self.log.torque_off_raises.append(servo_id)
                raise OSError("bus drop while clearing torque")
            self.servos[servo_id].torque = 0
            return COMM_SUCCESS, 0
        if address == SCSCL_TORQUE_ENABLE and value == 1:
            if servo_id in self.fail_enable:
                return COMM_TX_FAIL, 0
            self.servos[servo_id].torque = 1
            return COMM_SUCCESS, 0
        return COMM_SUCCESS, 0


def run_script(module, extra_argv, packet: FakePacket | None = None, hold_seconds: int = 5):
    FakePort.instances.clear()
    created = {}

    def packet_factory(port):
        inst = packet if packet is not None else FakePacket(port)
        inst.port = port
        FakePacket.last = inst
        created["packet"] = inst
        return inst

    argv = [
        str(SCRIPT),
        "--port",
        "MOCK1",
        "--frame-mounted-confirmed",
        "--hold-seconds",
        str(hold_seconds),
        *extra_argv,
    ]
    clock = FakeClock()
    stdout = io.StringIO()
    with (
        patch.object(sys, "argv", argv),
        patch.object(module, "PortHandler", FakePort),
        patch.object(module, "scscl", packet_factory),
        patch.object(module.time, "monotonic", clock.monotonic),
        patch.object(module.time, "sleep", clock.sleep),
        redirect_stdout(stdout),
    ):
        code = module.main()
    return code, stdout.getvalue(), created.get("packet"), FakePort.instances


class CenterHoldPairSafetyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_center_hold()

    def setUp(self):
        global HARDWARE_ACCESSED
        HARDWARE_ACCESSED = False
        FakePort.instances.clear()
        FakePacket.last = None

    def tearDown(self):
        self.assertFalse(HARDWARE_ACCESSED, "test opened or probed real hardware")

    def test_hardware_accessed_stays_false(self):
        code, _, packet, ports = run_script(self.module, [])
        self.assertFalse(HARDWARE_ACCESSED)
        self.assertEqual(code, 0)
        self.assertTrue(ports)
        self.assertEqual(ports[0].name, "MOCK1")
        self.assertNotIn("COM", ports[0].name.upper())
        self.assertIsNotNone(packet)

    def test_refuses_without_frame_mounted_confirmation(self):
        argv = [str(SCRIPT), "--port", "MOCK1", "--hold-seconds", "5"]
        stdout = io.StringIO()
        with (
            patch.object(sys, "argv", argv),
            patch.object(self.module, "PortHandler", FakePort),
            patch.object(self.module, "scscl", FakePacket),
            redirect_stdout(stdout),
        ):
            code = self.module.main()
        self.assertEqual(code, 2)
        self.assertIn("REFUSED", stdout.getvalue())
        self.assertEqual(FakePort.instances, [])

    def test_happy_path_writes_only_start_then_511_and_releases_both(self):
        code, out, packet, ports = run_script(self.module, ["--speed", "50"])
        self.assertEqual(code, 0)
        self.assertIn("PASS", out)
        self.assertTrue(ports[0].closed)
        goals = [item[1] for item in packet.log.write_pos]
        self.assertEqual(set(goals), {400, 600, ELECTRICAL_MIDPOINT})
        reference = [
            item for item in packet.log.write_pos if item[1] == ELECTRICAL_MIDPOINT
        ]
        self.assertEqual([item[0] for item in reference], [1, 2])
        self.assertTrue(all(item[3] == 50 for item in packet.log.write_pos))
        self.assertEqual(packet.log.torque_off_attempts, [1, 2])
        self.assertEqual({servo.torque for servo in packet.servos.values()}, {0})

    def test_missing_id1_writes_no_goal_and_does_not_enable_torque(self):
        packet = FakePacket(None)
        packet.fail_ping.add(1)
        code, out, packet, _ = run_script(self.module, [], packet=packet)
        self.assertEqual(code, 1)
        self.assertEqual(packet.log.write_pos, [])
        self.assertFalse(
            any(
                address == SCSCL_TORQUE_ENABLE and value == 1
                for _, address, value in packet.log.writes
            )
        )
        self.assertIn("ERROR", out)

    def test_missing_id2_writes_no_goal_and_does_not_enable_torque(self):
        packet = FakePacket(None)
        packet.fail_ping.add(2)
        code, out, packet, _ = run_script(self.module, [], packet=packet)
        self.assertEqual(code, 1)
        self.assertEqual(packet.log.write_pos, [])
        self.assertEqual(packet.log.pings, [1, 2])
        self.assertFalse(
            any(
                address == SCSCL_TORQUE_ENABLE and value == 1
                for _, address, value in packet.log.writes
            )
        )
        self.assertIn("ERROR", out)

    def test_missing_id_still_attempts_torque_off_on_both(self):
        """Any exit must torque-off both IDs so a leftover enable cannot linger."""
        packet = FakePacket(None)
        packet.fail_ping.add(2)
        _, _, packet, _ = run_script(self.module, [], packet=packet)
        self.assertEqual(sorted(packet.log.torque_off_attempts), [1, 2])

    def test_second_servo_enable_failure_does_not_reference_id2(self):
        packet = FakePacket(None)
        packet.fail_enable.add(2)
        code, out, packet, _ = run_script(self.module, [], packet=packet)
        self.assertEqual(code, 1)
        id2_refs = [
            item
            for item in packet.log.write_pos
            if item[0] == 2 and item[1] == ELECTRICAL_MIDPOINT
        ]
        self.assertEqual(id2_refs, [])
        self.assertIn("ERROR", out)

    def test_second_servo_enable_failure_torque_off_both(self):
        packet = FakePacket(None)
        packet.fail_enable.add(2)
        _, _, packet, _ = run_script(self.module, [], packet=packet)
        self.assertEqual(sorted(packet.log.torque_off_attempts), [1, 2])

    def test_partial_reference_write_aborts_before_hold(self):
        packet = FakePacket(None)
        packet.fail_write_pos_phase[2] = "reference"
        code, out, packet, _ = run_script(self.module, [], packet=packet)
        self.assertEqual(code, 1)
        self.assertNotIn("HOLDING", out)
        self.assertNotIn("PASS", out)
        self.assertTrue(packet.log.torque_off_attempts)

    def test_short_write_on_id2_reference_aborts(self):
        packet = FakePacket(None)
        packet.short_write_ids.add(2)
        code, out, packet, _ = run_script(self.module, [], packet=packet)
        self.assertEqual(code, 1)
        self.assertNotIn("HOLDING", out)
        self.assertIn("ERROR", out)

    def test_reference_timeout_aborts_and_releases(self):
        packet = FakePacket(None)
        packet.servos[1].never_arrive = True
        packet.servos[1].position = 400
        code, out, packet, _ = run_script(self.module, [], packet=packet)
        self.assertEqual(code, 1)
        self.assertIn("timeout", out.lower())
        self.assertEqual(packet.log.torque_off_attempts, [1, 2])

    def test_start_overtemp_writes_no_goal(self):
        packet = FakePacket(None)
        packet.servos[2].temperature = 50
        code, out, packet, _ = run_script(self.module, [], packet=packet)
        self.assertEqual(code, 1)
        self.assertEqual(packet.log.write_pos, [])
        self.assertIn("temperature", out.lower())

    def test_hold_overtemp_aborts(self):
        packet = FakePacket(None)

        def hook(bus, kind, value):
            if kind == "hold_cycle" and value == 1:
                bus.servos[1].temperature = 51

        packet.hold_hook = hook
        code, out, packet, _ = run_script(self.module, [], packet=packet, hold_seconds=10)
        self.assertEqual(code, 1)
        self.assertIn("unsafe hold", out.lower())
        self.assertEqual(packet.log.torque_off_attempts, [1, 2])

    def test_start_undervoltage_writes_no_goal(self):
        packet = FakePacket(None)
        packet.servos[1].voltage = 49
        code, out, packet, _ = run_script(self.module, [], packet=packet)
        self.assertEqual(code, 1)
        self.assertEqual(packet.log.write_pos, [])
        self.assertIn("voltage", out.lower())

    def test_hold_overvoltage_aborts(self):
        packet = FakePacket(None)

        def hook(bus, kind, value):
            if kind == "hold_cycle" and value == 1:
                bus.servos[2].voltage = 71

        packet.hold_hook = hook
        code, out, packet, _ = run_script(self.module, [], packet=packet, hold_seconds=10)
        self.assertEqual(code, 1)
        self.assertIn("unsafe hold", out.lower())
        self.assertEqual(packet.log.torque_off_attempts, [1, 2])

    def test_implausible_start_position_aborts_before_motion(self):
        packet = FakePacket(None)
        packet.servos[2].position = 1400
        code, out, packet, _ = run_script(self.module, [], packet=packet)
        self.assertEqual(code, 1)
        self.assertEqual(packet.log.write_pos, [])
        self.assertIn("implausible position", out.lower())

    def test_hold_position_drift_aborts(self):
        """A jump away from 511 during hold is a position fault, not a status print."""
        packet = FakePacket(None)

        def hook(bus, kind, value):
            if kind == "hold_cycle" and value == 1:
                bus.servos[1].position = 900

        packet.hold_hook = hook
        code, out, packet, _ = run_script(self.module, [], packet=packet, hold_seconds=10)
        self.assertEqual(code, 1)
        self.assertNotIn("PASS", out)
        self.assertTrue(packet.log.torque_off_attempts)

    def test_dropout_during_hold_aborts(self):
        packet = FakePacket(None)

        def hook(bus, kind, value):
            if kind == "hold_cycle" and value == 1:
                bus.fail_read_pos.add(2)

        packet.hold_hook = hook
        code, out, packet, _ = run_script(self.module, [], packet=packet, hold_seconds=10)
        self.assertEqual(code, 1)
        self.assertIn("ERROR", out)
        self.assertEqual(packet.log.torque_off_attempts, [1, 2])

    def test_ctrl_c_returns_130_and_releases_both(self):
        packet = FakePacket(None)

        def hook(bus, kind, value):
            if kind == "hold_cycle" and value == 1:
                raise KeyboardInterrupt

        packet.hold_hook = hook
        code, out, packet, ports = run_script(self.module, [], packet=packet)
        self.assertEqual(code, 130)
        self.assertIn("STOP", out)
        self.assertEqual(packet.log.torque_off_attempts, [1, 2])
        self.assertTrue(ports[0].closed)

    def test_torque_off_failure_on_id1_still_attempts_id2(self):
        packet = FakePacket(None)
        packet.raise_torque_off.add(1)
        code, _, packet, _ = run_script(self.module, [], packet=packet)
        self.assertEqual(code, 0)
        self.assertEqual(packet.log.torque_off_attempts, [1, 2])
        self.assertEqual(packet.log.torque_off_raises, [1])
        self.assertEqual(packet.servos[2].torque, 0)

    def test_refuses_excessive_speed_before_any_write(self):
        code, out, packet, ports = run_script(self.module, ["--speed", "2000"])
        self.assertEqual(code, 2)
        self.assertIn("REFUSED", out)
        self.assertEqual(ports, [])
        self.assertIsNone(packet)

    def test_refuses_zero_speed_before_any_write(self):
        # Feetech SCSCL speed=0 + time=0 is treated as maximum speed.
        code, out, packet, ports = run_script(self.module, ["--speed", "0"])
        self.assertEqual(code, 2)
        self.assertIn("REFUSED", out)
        self.assertEqual(ports, [])
        self.assertIsNone(packet)

    def test_refuses_unexpected_model_before_motion(self):
        packet = FakePacket(None)
        packet.servos[2].model = 99
        code, out, packet, _ = run_script(self.module, [], packet=packet)
        self.assertEqual(code, 1)
        self.assertEqual(packet.log.write_pos, [])
        self.assertIn("model", out.lower())

    def test_refuses_when_511_is_outside_angle_limits(self):
        packet = FakePacket(None)
        packet.servos[1].min_limit = 600
        packet.servos[1].max_limit = 1003
        code, out, packet, _ = run_script(self.module, [], packet=packet)
        self.assertEqual(code, 1)
        self.assertEqual(packet.log.write_pos, [])
        self.assertTrue(
            any(kind == "min_limit" for _, kind in packet.log.reads),
            "angle limits were never read",
        )

    def test_refuses_if_either_servo_already_has_torque(self):
        packet = FakePacket(None)
        packet.servos[2].torque = 1
        code, out, packet, _ = run_script(self.module, [], packet=packet)
        self.assertEqual(code, 1)
        self.assertEqual(packet.log.write_pos, [])
        self.assertTrue(any(kind == "torque" for _, kind in packet.log.reads))

    def test_does_not_import_production_pose_or_write_calibration(self):
        imported = []
        opened_for_write = []
        real_import = builtins.__import__
        real_open = builtins.open

        def guarded_import(name, *args, **kwargs):
            imported.append(name)
            root = name.split(".")[0]
            if root in {
                "finger_smoke_scs0009",
                "servo_safety_model",
                "action_safety_model",
                "grip_pose_bank",
                "run_offline_rehearsal",
            }:
                raise AssertionError(f"center_hold imported production module {name}")
            return real_import(name, *args, **kwargs)

        def guarded_open(file, mode="r", *args, **kwargs):
            text = str(file).replace("\\", "/").lower()
            if any(flag in mode for flag in ("w", "a", "x", "+")):
                opened_for_write.append((text, mode))
                if "calibration" in text or text.endswith(".csv"):
                    raise AssertionError(f"center_hold wrote calibration data: {file}")
            return real_open(file, mode, *args, **kwargs)

        with (
            patch.object(builtins, "__import__", guarded_import),
            patch.object(builtins, "open", guarded_open),
        ):
            code, _, _, _ = run_script(self.module, [])
        self.assertEqual(code, 0)
        self.assertEqual(opened_for_write, [])
        self.assertFalse(any("finger_smoke" in name for name in imported))
        self.assertFalse(any("servo_safety_model" in name for name in imported))


if __name__ == "__main__":
    unittest.main()
