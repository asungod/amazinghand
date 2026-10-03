"""Read-only Titan MAP/ELF function-level linkage evidence checker.

Module-name-only hits are not enough: required function/init symbols must appear.
Does not flash or rewrite Debug artifacts. Host GCC is never treated as ARM build.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

# Function-level evidence (task A). comm_init accepts RT-Thread init wrapper alias.
REQUIRED_FUNCTION_GROUPS: Tuple[Tuple[str, ...], ...] = (
    ("smart_hand_comm_init", "__rt_init_smart_hand_comm_init"),
    ("shp_parser_feed",),
    ("smart_hand_vision_state_init",),
    ("smart_hand_vision_state_note_vision",),
    ("smart_hand_vision_state_expire",),
    ("smart_hand_vision_state_invalidate",),
    ("smart_hand_sequence_guard_init",),
    ("smart_hand_sequence_guard_note",),
    ("smart_hand_sequence_guard_reset",),
    ("grip_policy_decide",),
    ("eight_servo_pose_bank_init",),
    ("eight_servo_pose_bank_resolve",),
    ("run_rehab_demo_once",),
    ("servo_bus_rehab_demo_request",),
    ("servo_bus_rehab_demo_get_status",),
    # AITRUST advisory telemetry (2026-09-23). These prove the encoder and the
    # send path really reached the image. Without them this check stays green
    # even if smart_hand_status_telemetry.c were dropped from the CDT makefile's
    # three lists -- the exact silent-no-link failure the project has hit before.
    ("smart_hand_aitrust_pack",),
    ("smart_hand_aitrust_vision_age_ms",),
    ("smart_hand_aitrust_due",),
    ("smart_hand_aitrust_link_init",),
    ("smart_hand_aitrust_note_attempt",),
    ("smart_hand_aitrust_note_sent",),
    ("smart_hand_aitrust_note_failed",),
    ("send_aitrust",),
    ("smart_hand_status_pack",),
)

# Kept for informational module presence; not sufficient alone.
REQUIRED_MODULE_MARKERS = (
    "smart_hand_uart",
    "smart_hand_protocol",
    "smart_hand_vision_state",
    "smart_hand_sequence_guard",
    "grip_policy",
    "eight_servo_pose_bank",
)

# Back-compat alias used by older tests/callers.
REQUIRED_MARKERS = REQUIRED_MODULE_MARKERS


def newest_mtime(paths: Iterable[Path]) -> float:
    times = [p.stat().st_mtime for p in paths if p.is_file()]
    if not times:
        raise FileNotFoundError("no source files available for staleness check")
    return max(times)


def _symbol_present(text: str, symbol: str) -> bool:
    """Match whole symbol tokens; avoid bare module-name false confidence."""
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(symbol) + r"(?![A-Za-z0-9_])", text) is not None


def find_missing_function_groups(
    map_text: str,
    groups: Sequence[Sequence[str]] = REQUIRED_FUNCTION_GROUPS,
) -> List[str]:
    """Return human-readable missing group labels (OR within a group)."""
    missing: List[str] = []
    for group in groups:
        if not any(_symbol_present(map_text, name) for name in group):
            missing.append(" or ".join(group))
    return missing


def find_missing_markers(map_text: str, markers: Sequence[str] = REQUIRED_MARKERS) -> List[str]:
    """Legacy module-name helper (not sufficient for pass)."""
    return [m for m in markers if not re.search(re.escape(m), map_text, re.IGNORECASE)]


def map_is_stale(map_path: Path, source_paths: Sequence[Path]) -> bool:
    if not map_path.is_file():
        raise FileNotFoundError(f"MAP not found: {map_path}")
    return map_path.stat().st_mtime + 1e-6 < newest_mtime(source_paths)


def run_nm_symbols(elf_path: Path, nm_tool: str = "arm-none-eabi-nm") -> Optional[str]:
    nm = shutil.which(nm_tool)
    if nm is None or not elf_path.is_file():
        return None
    try:
        proc = subprocess.run(
            [nm, "-C", str(elf_path)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout or ""


def evaluate_linkage(
    map_path: Path,
    source_paths: Sequence[Path],
    markers: Sequence[str] = REQUIRED_MARKERS,
    function_groups: Sequence[Sequence[str]] = REQUIRED_FUNCTION_GROUPS,
    elf_path: Optional[Path] = None,
    nm_output: Optional[str] = None,
    nm_tool: str = "arm-none-eabi-nm",
) -> dict:
    """Evaluate MAP (+ optional ELF nm) for function-level linkage evidence."""
    del markers  # module names alone are never enough to pass

    if not map_path.is_file():
        return {
            "ok": False,
            "reason": "map_missing",
            "missing_functions": [" or ".join(g) for g in function_groups],
            "missing_markers": list(REQUIRED_MODULE_MARKERS),
            "stale": True,
            "map_path": str(map_path),
            "evidence_mode": "none",
            "nm_available": False,
        }

    text = map_path.read_text(encoding="utf-8", errors="replace")
    missing_functions = find_missing_function_groups(text, function_groups)
    module_hits = find_missing_markers(text, REQUIRED_MODULE_MARKERS)

    try:
        stale = map_is_stale(map_path, source_paths)
    except FileNotFoundError as exc:
        return {
            "ok": False,
            "reason": str(exc),
            "missing_functions": missing_functions,
            "missing_markers": module_hits,
            "stale": True,
            "map_path": str(map_path),
            "evidence_mode": "map_only",
            "nm_available": False,
        }

    evidence_mode = "map_only"
    nm_available = False
    nm_missing: List[str] = []

    resolved_nm = nm_output
    if resolved_nm is None and elf_path is not None:
        resolved_nm = run_nm_symbols(elf_path, nm_tool=nm_tool)
    if resolved_nm is not None:
        nm_available = True
        evidence_mode = "map_and_elf_nm"
        nm_missing = find_missing_function_groups(resolved_nm, function_groups)

    # Pass requires: not stale, all function groups on MAP.
    # Optional nm: if available, also require symbols there; if unavailable, map_only OK.
    ok = (not stale) and (not missing_functions)
    if nm_available and nm_missing:
        ok = False

    if not map_path.is_file():
        reason = "map_missing"
    elif stale and missing_functions:
        reason = "stale_and_missing_functions"
    elif stale:
        reason = "stale_map"
    elif missing_functions:
        reason = "missing_functions"
    elif nm_available and nm_missing:
        reason = "elf_missing_functions"
    else:
        reason = "ok"

    # Detect module-name-only false confidence for diagnostics.
    modules_present_functions_missing = (not module_hits) and bool(missing_functions)

    return {
        "ok": ok,
        "reason": reason,
        "missing_functions": missing_functions,
        "missing_markers": module_hits,  # legacy field
        "modules_present_functions_missing": modules_present_functions_missing,
        "stale": stale,
        "map_path": str(map_path),
        "map_mtime": map_path.stat().st_mtime,
        "newest_source_mtime": newest_mtime(source_paths) if source_paths else None,
        "evidence_mode": evidence_mode,
        "nm_available": nm_available,
        "nm_missing_functions": nm_missing,
        "elf_path": str(elf_path) if elf_path else None,
    }


def default_studio_sources(studio_src: Path) -> List[Path]:
    names = [
        "smart_hand_uart.c",
        # The AITRUST encoder lives here and smart_hand_uart.c includes its
        # header, so its mtime decides staleness too -- leaving it out let the
        # MAP be stale with respect to the file this batch changed most.
        "smart_hand_status_telemetry.c",
        "smart_hand_status_telemetry.h",
        "smart_hand_protocol.c",
        "smart_hand_vision_state.c",
        "smart_hand_sequence_guard.c",
        "grip_policy.c",
        "eight_servo_pose_bank.c",
    ]
    return [studio_src / name for name in names]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check Titan MAP function-level linkage evidence"
    )
    parser.add_argument(
        "--map",
        default=r"D:\Micu\RTTWorkspace\titan_uart_test\Debug\rtthread.map",
    )
    parser.add_argument(
        "--studio-src",
        default=r"D:\Micu\RTTWorkspace\titan_uart_test\src",
    )
    parser.add_argument(
        "--elf",
        default=r"D:\Micu\RTTWorkspace\titan_uart_test\Debug\rtthread.elf",
        help="Optional ELF for arm-none-eabi-nm cross-check",
    )
    parser.add_argument("--nm-tool", default="arm-none-eabi-nm")
    args = parser.parse_args(argv)

    map_path = Path(args.map)
    studio_src = Path(args.studio_src)
    elf_path = Path(args.elf) if args.elf else None
    sources = [p for p in default_studio_sources(studio_src) if p.is_file()]
    result = evaluate_linkage(
        map_path,
        sources,
        elf_path=elf_path if elf_path and elf_path.is_file() else None,
        nm_tool=args.nm_tool,
    )

    print(f"map={result['map_path']}")
    print(
        f"ok={result['ok']} reason={result['reason']} stale={result['stale']} "
        f"evidence_mode={result['evidence_mode']} nm_available={result['nm_available']}"
    )
    if result.get("missing_functions"):
        print("missing_functions: " + ", ".join(result["missing_functions"]))
    if result.get("modules_present_functions_missing"):
        print(
            "note: module names appear in MAP but required function symbols are missing "
            "(module-name-only is not sufficient)"
        )
    if result.get("nm_missing_functions"):
        print("nm_missing_functions: " + ", ".join(result["nm_missing_functions"]))
    if not result["ok"]:
        if result["reason"] == "map_missing":
            print(
                "ARM MAP missing: Studio Refresh/Clean/Build after syncing .c files. "
                "Host GCC is not an ARM build."
            )
        elif result["stale"]:
            print(
                "MAP is older than synced Studio sources — rebuild required "
                "(do not hand-edit Debug makefiles)."
            )
        return 1
    print("Titan function-level linkage evidence check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
