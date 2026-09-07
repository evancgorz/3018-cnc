"""CLI for hardware-free digital-twin evidence runs."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .scenarios import built_in_scenarios, run_headless_scenario
from .stock import load_step_target
from .trace import replay_scenario_trace


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic TTC 3018 digital-twin scenarios")
    parser.add_argument("--all", action="store_true", help="run every built-in scenario")
    parser.add_argument("--scenario", action="append", default=[], help="run a named scenario")
    parser.add_argument("--output", type=Path, required=True, help="evidence output directory")
    parser.add_argument("--replay", type=Path, help="replay a stored built-in scenario trace")
    parser.add_argument("--replay-scenario", help="scenario name when the stored trace lacks scenario_start metadata")
    parser.add_argument("--workpiece", type=Path, default=Path("examples/showcase-pocket-island.step"),
                        help="STEP observation fixture to validate (default: pocket/island)")
    args = parser.parse_args(argv)
    if args.replay is not None:
        result = replay_scenario_trace(args.replay, scenario_name=args.replay_scenario)
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "replay.json").write_text(json.dumps({"schema_version": 1, **result}, indent=2) + "\n", encoding="utf-8")
        status = "PASS" if result["matched"] else "FAIL"
        (args.output / "replay.md").write_text(
            "# Digital twin replay\n\n"
            f"Scenario: {result['scenario']}\n"
            f"Seed: {result['seed']}\n"
            f"Result: {status}\n"
            f"First difference: {result['first_difference'] or 'none'}\n",
            encoding="utf-8",
        )
        return 0 if result["matched"] else 1
    scenarios = built_in_scenarios()
    selected = scenarios if args.all or not args.scenario else tuple(item for item in scenarios if item.name in args.scenario)
    if not selected:
        parser.error("No matching scenario")
    results = [run_headless_scenario(item) for item in selected]
    args.output.mkdir(parents=True, exist_ok=True)
    workpiece_metadata = None
    if args.workpiece.exists():
        workpiece_metadata = asdict(load_step_target(args.workpiece))
    # Keep machine-readable evidence self-contained: summary carries final
    # snapshots/assertions while each scenario gets a replayable normalized
    # trace and a small final-state artifact for CI consumers.
    summary_results = []
    for item in results:
        result = dict(item.__dict__)
        result["trace_events"] = list(item.trace_events)
        result["hazards"] = list(item.hazards)
        summary_results.append(result)
        (args.output / f"{item.name}.trace.json").write_text(
            json.dumps({"schema_version": 1, "events": list(item.trace_events)}, indent=2) + "\n",
            encoding="utf-8",
        )
        (args.output / f"{item.name}.final.json").write_text(
            json.dumps({"schema_version": 1, "scenario": item.name,
                        "passed": item.passed, "state": item.final_state,
                        "machine_position": item.final_position,
                        "assertions": item.assertions, "failures": item.failures,
                        "trace_digest": item.trace_digest,
                        "hazards": list(item.hazards),
                        "stock_metrics": item.stock_metrics}, indent=2) + "\n",
            encoding="utf-8",
        )
    payload = {"schema_version": 1, "scenario_count": len(results),
               "passed": all(item.passed for item in results),
               "workpiece": workpiece_metadata, "results": summary_results}
    (args.output / "summary.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    lines = ["# Digital twin verification", "", f"Scenarios: {len(results)}",
             f"Passed: {sum(item.passed for item in results)}"]
    if workpiece_metadata:
        lines.extend(["", f"STEP fixture: `{workpiece_metadata['path']}`",
                      f"Dimensions: {workpiece_metadata['width']:.3f} × {workpiece_metadata['height']:.3f} × {workpiece_metadata['thickness']:.3f} mm",
                      f"Features: {workpiece_metadata['feature_count']} (loops: {workpiece_metadata['loop_count']})"])
    lines.extend(["", "| Scenario | Result | Final state | Trace |", "|---|---|---|---|"])
    lines.extend(f"| {item.name} | {'PASS' if item.passed else 'FAIL'} | {item.final_state} | `{item.trace_digest}` |" for item in results)
    (args.output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
