"""Assemble and verify a review-only sequence of independently loaded jobs."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from ..application.job_provenance import read_review_bundle


def _stages(root: Path, paths: list[str]) -> list[dict]:
    if not 2 <= len(paths) <= 16:
        raise ValueError("A sequence requires 2 to 16 separate pass bundles")
    result = []
    previous_stock = previous_origin = None
    for index, relative in enumerate(paths):
        if not isinstance(relative, str) or "\\" in relative or ":" in relative:
            raise ValueError("Use relative pass paths like engraving/report.json")
        parts = relative.split("/")
        if len(parts) != 2 or parts[0] in ("", ".", "..") or parts[1] != "report.json":
            raise ValueError("Each pass must be a child directory's report.json")
        path = root.joinpath(*parts)
        if path.resolve() != path or not path.is_file():
            raise ValueError(f"Missing local pass report: {relative}")
        program, report, digest = read_review_bundle(path)
        stock, origin, tool = report.get("stock_mm"), report.get("origin"), report.get("tool")
        if not isinstance(stock, list) or len(stock) != 3 or not all(
            type(value) in (int, float) and math.isfinite(value) and value > 0 for value in stock
        ):
            raise ValueError(f"Pass {index + 1} needs declared stock dimensions")
        if not isinstance(origin, str) or not origin.strip() or not isinstance(tool, dict) or not tool.get("type"):
            raise ValueError(f"Pass {index + 1} needs declared origin and tool; regenerate older reports")
        if index and (stock != previous_stock or origin != previous_origin):
            raise ValueError(f"Pass {index + 1} uses different stock or work origin")
        if report["kind"] == "step-profile" and index != len(paths) - 1:
            raise ValueError("The tabbed cutout must be the final pass")
        if any(item["program_sha256"] == program.source_sha256 for item in result):
            raise ValueError("Each pass must use distinct G-code")
        previous_stock, previous_origin = stock, origin
        result.append({
            "report": relative,
            "report_sha256": digest,
            "program_sha256": program.source_sha256,
            "kind": report["kind"],
            "tool": tool,
            "stock_mm": stock,
            "origin": origin,
            "required_setup": [
                "Verify the installed tool and stock for this pass.",
                "Preserve the fixture and shared XY datum across passes.",
                "Establish work Z for the installed tool before starting.",
            ],
        })
    return result


def create(path: Path, frame: str, reports: list[str]) -> dict:
    """Record the exact passes. The output is review evidence, never a job."""
    if not frame.strip():
        raise ValueError("Describe the shared fixture and XY datum with --frame")
    path = path.resolve()
    value = {
        "schema_version": 1,
        "status": "review-only",
        "shared_xy_frame": frame.strip(),
        "passes": _stages(path.parent, reports),
    }
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write("\n")
    return value


def inspect(path: Path) -> dict:
    """Reject a sequence whose pass reports or assets changed since assembly."""
    path = path.resolve()
    with path.open("rb") as handle:
        raw = handle.read(128 * 1024 + 1)
    if len(raw) > 128 * 1024:
        raise ValueError("Sequence report exceeds the size limit")
    value = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or (
        value["schema_version"] != 1 or value.get("status") != "review-only"
        or not isinstance(value.get("shared_xy_frame"), str) or not value["shared_xy_frame"].strip()
        or not isinstance(value.get("passes"), list)
    ):
        raise ValueError("Choose a valid v1 review-only sequence")
    try:
        paths = [item["report"] for item in value["passes"]]
    except (TypeError, KeyError) as exc:
        raise ValueError("Each sequence pass needs a report path") from exc
    if _stages(path.parent, paths) != value["passes"]:
        raise ValueError("Sequence evidence changed; review and assemble a new sequence")
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    assemble = commands.add_parser("create", help="bind ordered pass bundles to a new sequence")
    assemble.add_argument("path", type=Path)
    assemble.add_argument("--frame", required=True)
    assemble.add_argument("reports", nargs="+")
    verify = commands.add_parser("inspect", help="verify all passes against the sequence")
    verify.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    try:
        result = create(args.path, args.frame, args.reports) if args.command == "create" else inspect(args.path)
    except (OSError, ValueError, RecursionError) as exc:
        parser.exit(2, f"CAM sequence rejected: {exc}\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
