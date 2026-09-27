"""Run a realistic recorded supply-chain incident through the full graph."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from on_call_assistant.agent.graph import create_graph
from on_call_assistant.evaluation.report import capture_actual, write_reports
from on_call_assistant.evaluation.trajectory import evaluate_trajectory

from .fixtures import FixtureModel, RecordedTools
from .verifier import verify_outcome


ROOT = Path(__file__).resolve().parent


def run_case(case: dict[str, Any], *, live_model: bool = False,
             tools: RecordedTools | None = None, model: Any | None = None) -> dict[str, Any]:
    tools = tools or RecordedTools()
    selected_model = model if model is not None else (None if live_model else FixtureModel())
    graph = create_graph(ROOT / "harness", tools=tools, model=selected_model)
    state = graph.invoke({"request": case["input"]},
                         config={"configurable": {"thread_id": f"supply-chain-{case['id']}"}})
    trajectory = evaluate_trajectory(state, case["expected_trajectory"])
    outcome = verify_outcome(case, state, tools)
    return {"id": case["id"], "capability": state.get("capability"),
            "passed": trajectory["reward"] == 1.0 and outcome["passed"],
            "trajectory": trajectory, "outcome": outcome,
            "answer": state.get("answer"), "tasks": state.get("tasks", []),
            "trace": state.get("trace", []), "policy_tokens": state.get("policy_tokens", 0)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay the supply-chain OCA example")
    parser.add_argument("--case", choices=["all", "account-material-issue", "release-material-issue"], default="all")
    parser.add_argument("--live-model", action="store_true", help="use the configured model with recorded tools")
    parser.add_argument("--json", action="store_true", help="print full machine-readable results")
    parser.add_argument("--report-json", type=Path, help="save expected and actual routes as JSON")
    parser.add_argument("--report-html", type=Path, help="save a visual expected/actual trajectory report")
    args = parser.parse_args()
    cases = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    results = []
    selected_cases = []
    for case in cases:
        if args.case != "all" and case["id"] != args.case:
            continue
        selected_cases.append(case)
        if args.live_model:
            print(f"Running {case['id']} with live model...", file=sys.stderr, flush=True)
        try:
            results.append(run_case(case, live_model=args.live_model))
        except Exception as exc:
            results.append({"id": case["id"], "passed": False, "error": str(exc)})
        if args.live_model:
            print(f"Finished {case['id']}: {'PASS' if results[-1]['passed'] else 'FAIL'}",
                  file=sys.stderr, flush=True)
    records = []
    for case, result in zip(selected_cases, results):
        verdict = result.get("trajectory", {"reward": 0.0, "failure_tags": ["execution_error"],
                                            "error": result.get("error", "unknown error")})
        records.append({"id": case["id"], "request": case["input"].get("text", ""),
                        "expected_trajectory": case["expected_trajectory"],
                        "actual": capture_actual(result) if "trajectory" in result else None,
                        "verdict": verdict})
    write_reports(records, json_path=args.report_json, html_path=args.report_html)
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for result in results:
            label = "PASS" if result["passed"] else "FAIL"
            print(f"{label} {result['id']}")
            if result.get("error"):
                print(f"  Error: {result['error']}")
                continue
            print(f"  {result['answer'].get('summary', '')}")
            print(f"  Trajectory: {result['trajectory']['reward']:.0f}; outcome: {'pass' if result['outcome']['passed'] else 'fail'}")
            print("  Tasks: " + ", ".join(f"{task['id']}={task['status']}" for task in result["tasks"]))
            failures = result["trajectory"]["failure_tags"] + result["outcome"]["failure_tags"]
            if failures:
                print("  Failed checks: " + ", ".join(failures))
    if not all(item["passed"] for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
