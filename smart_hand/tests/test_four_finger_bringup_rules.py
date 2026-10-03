import copy
import unittest

from host.four_finger_bringup_rules import (
    CAL_PENDING,
    CAL_VERIFIED,
    ENUM_PENDING,
    ENUM_VERIFIED,
    validate_bringup_record,
    validate_gate6_readiness,
    validate_power_record,
    validate_role_records,
    validate_stop_record,
)
from host.four_finger_config_rules import EXPECTED_FOUR_FINGER_ROLES


def pending_record():
    return {
        "current_gate": 0,
        "requested_gate": None,
        "hardware_accessed": False,
        "mechanical_complete": False,
        "mechanical_evidence": "",
        "roles": [
            {
                "role": role,
                "servo_id": None,
                "enumeration_status": ENUM_PENDING,
                "readback_ok": False,
                "enumeration_evidence": "",
                "calibration_status": CAL_PENDING,
                "direction_sign": None,
                "center_raw": None,
                "soft_min_raw": None,
                "soft_max_raw": None,
                "calibration_evidence": "",
            }
            for role in EXPECTED_FOUR_FINGER_ROLES
        ],
        "power": {
            "external_6v_enabled": False,
            "profile_approved": False,
            "voltage_v": None,
            "current_limit_a": None,
            "operator_present": False,
            "emergency_disconnect_ready": False,
            "approval_evidence": "",
        },
        "stop": {
            "reason": "NONE",
            "stop_latched": False,
            "motion_authorized": False,
            "next_gate_authorized": False,
            "evidence": "",
        },
    }


def ready_gate6_record():
    record = pending_record()
    record.update(
        current_gate=5,
        requested_gate=6,
        hardware_accessed=True,
        mechanical_complete=True,
        mechanical_evidence="fixture://mechanical-review",
    )
    for servo_id, row in enumerate(record["roles"], start=101):
        row.update(
            servo_id=servo_id,
            enumeration_status=ENUM_VERIFIED,
            readback_ok=True,
            enumeration_evidence=f"fixture://enum/{row['role']}",
            calibration_status=CAL_VERIFIED,
            direction_sign=1,
            center_raw=511,
            soft_min_raw=400,
            soft_max_raw=600,
            calibration_evidence=f"fixture://cal/{row['role']}",
        )
    record["power"].update(
        profile_approved=True,
        voltage_v=6.0,
        current_limit_a=1.0,
        operator_present=True,
        emergency_disconnect_ready=True,
        approval_evidence="fixture://power-profile",
    )
    return record


class FourFingerBringupRuleTests(unittest.TestCase):
    def test_pending_template_is_structurally_valid_but_not_ready(self):
        record = pending_record()
        self.assertEqual(validate_bringup_record(record), [])
        ok, errors = validate_gate6_readiness(record)
        self.assertFalse(ok)
        self.assertIn("Gate 6 review requires an explicit 5 -> 6 request", errors)
        self.assertIn("Gate 6 review requires all 8 read-only enumerations", errors)

    def test_complete_synthetic_gate6_record_passes(self):
        ok, errors = validate_gate6_readiness(ready_gate6_record())
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_gate_transition_cannot_skip_or_reverse(self):
        for requested in (3, 7):
            record = pending_record()
            record["current_gate"] = 5
            record["requested_gate"] = requested
            self.assertIn(
                "requested_gate must not skip or reverse a Gate",
                validate_bringup_record(record),
            )

    def test_verified_ids_must_be_unique(self):
        record = ready_gate6_record()
        record["roles"][1]["servo_id"] = record["roles"][0]["servo_id"]
        self.assertIn(
            "verified servo_id values must be unique",
            validate_role_records(record["roles"]),
        )

    def test_verified_enumeration_requires_readback_and_evidence(self):
        record = ready_gate6_record()
        row = record["roles"][0]
        row["readback_ok"] = False
        row["enumeration_evidence"] = ""
        errors = validate_role_records(record["roles"])
        self.assertIn(
            "F1_PROXIMAL: verified enumeration requires readback_ok=true", errors
        )
        self.assertIn("F1_PROXIMAL: verified enumeration requires evidence", errors)

    def test_calibration_requires_enumeration_and_valid_raw_bounds(self):
        record = ready_gate6_record()
        row = record["roles"][0]
        row["enumeration_status"] = ENUM_PENDING
        row["direction_sign"] = 0
        row["soft_min_raw"] = 700
        row["center_raw"] = 511
        row["soft_max_raw"] = 600
        errors = validate_role_records(record["roles"])
        self.assertIn("F1_PROXIMAL: calibration requires verified enumeration", errors)
        self.assertIn("F1_PROXIMAL: direction_sign must be -1 or 1", errors)
        self.assertIn(
            "F1_PROXIMAL: calibration must satisfy 0 <= min <= center <= max <= 1023",
            errors,
        )

    def test_external_power_requires_approved_profile_and_manual_controls(self):
        power = pending_record()["power"]
        power["external_6v_enabled"] = True
        errors = validate_power_record(power)
        self.assertIn("external 6V requires an approved power profile", errors)
        self.assertIn("external 6V requires operator_present=true", errors)
        self.assertIn("external 6V requires emergency_disconnect_ready=true", errors)

    def test_approved_power_profile_requires_explicit_positive_values(self):
        power = pending_record()["power"]
        power["profile_approved"] = True
        errors = validate_power_record(power)
        self.assertIn("approved power profile requires positive voltage_v", errors)
        self.assertIn("approved power profile requires positive current_limit_a", errors)
        self.assertIn("approved power profile requires approval evidence", errors)

    def test_abnormal_stop_must_latch_and_deenergize(self):
        record = ready_gate6_record()
        stop = record["stop"]
        stop.update(
            reason="ABNORMAL_HEAT",
            stop_latched=False,
            motion_authorized=True,
            next_gate_authorized=True,
            evidence="",
        )
        record["power"]["external_6v_enabled"] = True
        errors = validate_stop_record(stop, record["power"])
        self.assertIn("abnormal stop reason requires stop_latched=true", errors)
        self.assertIn("latched stop requires external 6V off", errors)
        self.assertIn("latched stop requires motion_authorized=false", errors)
        self.assertIn("latched stop requires next_gate_authorized=false", errors)
        self.assertIn("latched stop requires evidence", errors)

    def test_properly_latched_stop_is_a_valid_record_but_blocks_gate6(self):
        record = ready_gate6_record()
        record["stop"].update(
            reason="MANUAL_STOP",
            stop_latched=True,
            motion_authorized=False,
            next_gate_authorized=False,
            evidence="fixture://manual-stop",
        )
        self.assertEqual(validate_bringup_record(record), [])
        ok, errors = validate_gate6_readiness(record)
        self.assertFalse(ok)
        self.assertIn("Gate 6 review is blocked by a latched stop", errors)

    def test_partial_enumeration_and_calibration_block_gate6(self):
        record = ready_gate6_record()
        record["roles"][7].update(
            servo_id=None,
            enumeration_status=ENUM_PENDING,
            readback_ok=False,
            enumeration_evidence="",
            calibration_status=CAL_PENDING,
            direction_sign=None,
            center_raw=None,
            soft_min_raw=None,
            soft_max_raw=None,
            calibration_evidence="",
        )
        ok, errors = validate_gate6_readiness(record)
        self.assertFalse(ok)
        self.assertIn("Gate 6 review requires all 8 read-only enumerations", errors)
        self.assertIn("Gate 6 review requires all 8 verified calibrations", errors)

    def test_gate6_requires_real_session_and_mechanical_evidence(self):
        record = ready_gate6_record()
        record["hardware_accessed"] = False
        record["mechanical_evidence"] = ""
        ok, errors = validate_gate6_readiness(record)
        self.assertFalse(ok)
        self.assertIn("Gate 6 review requires a real hardware session record", errors)
        self.assertIn("mechanical completion requires evidence", errors)


if __name__ == "__main__":
    unittest.main()
