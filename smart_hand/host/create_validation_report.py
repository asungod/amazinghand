"""Run local checks and archive evidence without requiring Git or network access."""

import argparse
import datetime
import hashlib
import platform
import re
import subprocess
import sys
from pathlib import Path


ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
MAIX_FILES = (
    "main.py",
    "protocol.py",
    "link_monitor.py",
    "target_tracker.py",
    "vision_source.py",
)
TITAN_FILES = (
    "smart_hand_protocol.c",
    "smart_hand_protocol.h",
    "smart_hand_uart.c",
)


def sha256_record(label, path):
    if not path.is_file():
        return {"label": label, "path": str(path), "sha256": "MISSING", "bytes": -1}
    return {
        "label": label,
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
        "bytes": path.stat().st_size,
    }


def hash_table(records):
    lines = ["| File | Bytes | SHA-256 |", "|---|---:|---|"]
    for record in records:
        byte_text = str(record["bytes"]) if record["bytes"] >= 0 else "missing"
        lines.append(
            "| `{}` | {} | `{}` |".format(
                record["label"], byte_text, record["sha256"]
            )
        )
    return "\n".join(lines)


def build_report(
    timestamp,
    check_returncode,
    check_output,
    maix_records,
    titan_records,
    studio_records,
    studio_project,
):
    result = "PASS" if check_returncode == 0 else "FAIL"
    clean_output = ANSI_ESCAPE.sub("", check_output).rstrip()
    return """# Smart Hand Local Validation Report

- Generated: `{timestamp}`
- Result: `{result}`
- Host: `{host}`
- Python: `{python}`
- Repository mode: local files only; no Git or network action performed
- Studio project checked: `{studio_project}`

## Command

```powershell
pwsh -File host\\run_all_checks.ps1
```

## Maix Application Hashes

{maix_table}

## Titan Canonical Hashes

{titan_table}

## Titan Studio Hashes

{studio_table}

## Check Output

```text
{check_output}
```
""".format(
        timestamp=timestamp,
        result=result,
        host=platform.platform(),
        python=sys.version.replace("\n", " "),
        studio_project=studio_project,
        maix_table=hash_table(maix_records),
        titan_table=hash_table(titan_records),
        studio_table=hash_table(studio_records),
        check_output=clean_output,
    )


def run_checks(project_root, studio_project):
    completed = subprocess.run(
        [
            "pwsh",
            "-File",
            str(project_root / "host" / "run_all_checks.ps1"),
            "-StudioProject",
            str(studio_project),
        ],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = completed.stdout
    if completed.stderr:
        if output and not output.endswith("\n"):
            output += "\n"
        output += completed.stderr
    return completed.returncode, output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--studio-project",
        type=Path,
        default=Path(r"D:\Micu\RTTWorkspace\titan_uart_test"),
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    now = datetime.datetime.now().astimezone()
    output_path = args.output
    if output_path is None:
        output_path = project_root / "validation_reports" / (
            "validation_{}.md".format(now.strftime("%Y%m%d_%H%M%S"))
        )
    elif not output_path.is_absolute():
        output_path = project_root / output_path

    returncode, check_output = run_checks(project_root, args.studio_project)
    maix_records = [
        sha256_record(name, project_root / "maixcam2" / name) for name in MAIX_FILES
    ]
    titan_records = [
        sha256_record(name, project_root / "titan_rtthread" / name)
        for name in TITAN_FILES
    ]
    studio_records = [
        sha256_record(name, args.studio_project / "src" / name) for name in TITAN_FILES
    ]
    report = build_report(
        now.isoformat(timespec="seconds"),
        returncode,
        check_output,
        maix_records,
        titan_records,
        studio_records,
        str(args.studio_project),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print("Validation report written to", output_path)
    print("Validation result:", "PASS" if returncode == 0 else "FAIL")
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
