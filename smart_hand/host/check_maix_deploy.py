"""Read-only preflight for the MaixCAM2 application files and configuration."""

import argparse
import ast
import hashlib
from pathlib import Path


REQUIRED_FILES = (
    "main.py",
    "protocol.py",
    "link_monitor.py",
    "target_tracker.py",
    "vision_source.py",
    "status_snapshot.py",
    "rehab_train.py",
    "rehab_hand_source.py",
    "sign_lesson.py",
    "sign_sequence.py",
    "gesture_classifier.py",
    "gesture_features.py",
    "web_stream.py",
    "rehab_goal.py",
    "rehab_imitation.py",
    "rehab_quality.py",
    "rehab_session_log.py",
    "hand_rehab_tracker.py",
)
REQUIRED_LOCAL_IMPORTS = {
    "link_monitor",
    "protocol",
    "status_snapshot",
    "rehab_train",
    "rehab_hand_source",
    "sign_lesson",
    "rehab_goal",
    "rehab_imitation",
    "rehab_quality",
    "rehab_session_log",
    "target_tracker",
    "vision_source",
}
SUPPORTED_MODES = ("mock", "yolo11", "disabled")


def top_level_constants(tree):
    constants = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        try:
            constants[target.id] = ast.literal_eval(node.value)
        except (ValueError, TypeError):
            continue
    return constants


def validate_config(config, expected_mode):
    errors = []
    if config.get("UART_DEVICE") != "/dev/ttyS2":
        errors.append("UART_DEVICE must remain /dev/ttyS2 for B0/B1 front UART2")
    if config.get("UART_BAUD") != 115200:
        errors.append("UART_BAUD must remain 115200 for the current protocol")

    mode = config.get("VISION_MODE")
    if mode not in SUPPORTED_MODES:
        errors.append("VISION_MODE must be one of {}".format(SUPPORTED_MODES))
    if expected_mode is not None and mode != expected_mode:
        errors.append(
            "VISION_MODE is {!r}, expected {!r}".format(mode, expected_mode)
        )

    positive_names = (
        "TARGET_STABLE_FRAMES",
        "TARGET_STALE_TIMEOUT_MS",
        "PING_INTERVAL_MS",
        "VISION_INTERVAL_MS",
        "ACK_TIMEOUT_MS",
        "STATS_INTERVAL_MS",
    )
    for name in positive_names:
        value = config.get(name)
        if type(value) not in (int, float) or value <= 0:
            errors.append("{} must be positive".format(name))

    process_interval = config.get("VISION_PROCESS_INTERVAL_MS")
    if type(process_interval) not in (int, float) or process_interval < 0:
        errors.append("VISION_PROCESS_INTERVAL_MS must not be negative")
    match_iou = config.get("TARGET_MATCH_IOU")
    if type(match_iou) not in (int, float) or not 0.0 <= match_iou <= 1.0:
        errors.append("TARGET_MATCH_IOU must be between 0 and 1")
    confidence = config.get("YOLO_CONFIDENCE_THRESHOLD")
    if type(confidence) not in (int, float) or not 0.0 <= confidence <= 1.0:
        errors.append("YOLO_CONFIDENCE_THRESHOLD must be between 0 and 1")
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-mode", choices=SUPPORTED_MODES)
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    maix_root = project_root / "maixcam2"
    errors = []
    parsed = {}

    for name in REQUIRED_FILES:
        path = maix_root / name
        if not path.is_file():
            errors.append("missing required file: {}".format(path))
            continue
        try:
            parsed[name] = ast.parse(path.read_text(encoding="utf-8"), filename=name)
        except (OSError, SyntaxError) as exc:
            errors.append("cannot parse {}: {}".format(path, exc))

    main_tree = parsed.get("main.py")
    config = {}
    if main_tree is not None:
        local_imports = {
            node.module
            for node in ast.walk(main_tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        missing_imports = sorted(REQUIRED_LOCAL_IMPORTS - local_imports)
        if missing_imports:
            errors.append(
                "main.py is missing local imports: {}".format(", ".join(missing_imports))
            )
        config = top_level_constants(main_tree)
        errors.extend(validate_config(config, args.expected_mode))

    if errors:
        print("Maix deploy preflight failed:")
        for error in errors:
            print("-", error)
        return 1

    print(
        "Maix config: mode={} uart={} baud={} process_ms={} send_ms={} "
        "stable_frames={} stale_ms={} match_iou={}".format(
            config["VISION_MODE"],
            config["UART_DEVICE"],
            config["UART_BAUD"],
            config["VISION_PROCESS_INTERVAL_MS"],
            config["VISION_INTERVAL_MS"],
            config["TARGET_STABLE_FRAMES"],
            config["TARGET_STALE_TIMEOUT_MS"],
            config["TARGET_MATCH_IOU"],
        )
    )
    print("Required Maix application files:")
    for name in REQUIRED_FILES:
        path = maix_root / name
        digest = hashlib.sha256(path.read_bytes()).hexdigest().upper()
        print("{}  {}  {} bytes".format(digest, name, path.stat().st_size))
    print("MAIX DEPLOY PREFLIGHT PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
