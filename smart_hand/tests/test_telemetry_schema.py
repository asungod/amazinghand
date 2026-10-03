import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))

from telemetry_schema import (  # noqa: E402
    TELEMETRY_SCHEMA_NAME,
    TELEMETRY_SCHEMA_VERSION,
    build_telemetry,
    telemetry_json,
    validate_telemetry,
)
import telemetry_schema as telemetry_schema_module  # noqa: E402


class TelemetrySchemaTests(unittest.TestCase):
    def test_complete_v1_document_covers_preview_ai_training_titan_and_health(self):
        document = build_telemetry(
            1234,
            frame={"sequence": 7, "available": True, "stale": False, "age_ms": 20, "dropped": 3, "encoding_fault": None},
            ai={"model": "yolo11n", "mode": "yolo11", "confidence_pct": 96, "detections": 2, "inference_ms": 31, "inference_fps": 32.2, "target": "bottle"},
            hand={"pose": "OPEN", "openness_pct": 91.2, "valid_frame_pct": 98.0},
            training={"phase": "running", "repetitions": 2, "goal_repetitions": 5, "completion_pct": 40, "quality": {"status": "OK", "rhythm": "NORMAL", "hold": "OK"}},
            titan={"link": "online", "rtt_ms": 28, "action": "CYLINDRICAL", "reason": "accepted", "gate": {"present": True, "armed": False, "fault": False}},
            stale={"vision": False, "titan_status": False},
            faults={"uart": False, "jpeg": False},
        )

        self.assertEqual(document["schema"], TELEMETRY_SCHEMA_NAME)
        self.assertEqual(document["schema_version"], TELEMETRY_SCHEMA_VERSION)
        self.assertEqual(json.loads(telemetry_json(document))["titan"]["rtt_ms"], 28)
        self.assertEqual(document["ai"]["detections"], 2)
        self.assertEqual(document["hand"]["pose"], "OPEN")
        self.assertEqual(document["training"]["completion_pct"], 40)

    def test_invalid_values_fail_closed(self):
        document = build_telemetry(1)
        document["ai"]["confidence_pct"] = 101
        with self.assertRaises(ValueError):
            validate_telemetry(document)

        document = build_telemetry(1)
        document["health"]["faults"] = {"uart": "unknown"}
        with self.assertRaises(ValueError):
            validate_telemetry(document)

        document = build_telemetry(1)
        document["schema_version"] = 2
        with self.assertRaises(ValueError):
            validate_telemetry(document)

    def test_unknown_fields_are_rejected_and_cannot_leak_to_wire_json(self):
        with self.assertRaises(ValueError):
            build_telemetry(1, ai={"internal_debug": "must_not_serialize"})

        document = build_telemetry(1)
        document["hand"]["raw_landmarks"] = [1, 2, 3]
        with self.assertRaises(ValueError):
            telemetry_json(document)

    def test_reduced_maix_json_without_keyword_arguments_falls_back_to_bytes(self):
        class ReducedJson:
            calls = []

            @classmethod
            def dumps(cls, value, **kwargs):
                cls.calls.append(kwargs)
                if kwargs:
                    raise TypeError("keyword arguments unsupported")
                return json.dumps(value, separators=(",", ":"))

        document = build_telemetry(1)
        with patch.object(telemetry_schema_module, "json", ReducedJson):
            payload = telemetry_schema_module.telemetry_json(document)

        self.assertEqual(ReducedJson.calls, [
            {"separators": (",", ":"), "sort_keys": True},
            {"separators": (",", ":")},
            {},
        ])
        self.assertIsInstance(payload, bytes)
        decoded = json.loads(payload)
        self.assertIs(validate_telemetry(decoded), decoded)


if __name__ == "__main__":
    unittest.main()
