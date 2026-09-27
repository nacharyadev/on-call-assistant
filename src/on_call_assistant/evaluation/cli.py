"""Run a dry-run pathway suite or verify an RRSI trial from stdin."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..agent.graph import create_graph
from .captured_flows import RecordedFlowTools
from .dry_run import DryRunTools
from .report import capture_actual, write_reports
from .trajectory import evaluate_trajectory


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate OCA's workflow trajectory")
    subparsers = parser.add_subparsers(dest="mode", required=True)
    subparsers.add_parser("verify-rrsi", help="read an RRSI verifier request from stdin")
    suite = subparsers.add_parser("run-suite", help="run pathway cases with mocked tools")
    suite.add_argument("cases", type=Path)
    suite.add_argument("--harness", type=Path, required=True)
    suite.add_argument("--report-json", type=Path, help="save expectations, verdicts, and actual routes as JSON")
    suite.add_argument("--report-html", type=Path, help="save a self-contained expected/actual visual report")
    replay = subparsers.add_parser("replay-case", help="replay one manually captured live case locally")
    replay.add_argument("case", type=Path)
    replay.add_argument("--harness", type=Path, required=True)
    replay.add_argument("--report-json", type=Path, help="save the expected and actual route as JSON")
    replay.add_argument("--report-html", type=Path, help="save a self-contained expected/actual report")
    args = parser.parse_args()
    if args.mode == "verify-rrsi":
        payload = json.load(sys.stdin)
        expectation = payload["task"].get("expected_trajectory", {})
        if not expectation:
            raise ValueError("task needs expected_trajectory")
        verdict = evaluate_trajectory(payload["agent_output"], expectation)
        print(json.dumps({"reward": verdict["reward"], "failure_tags": verdict["failure_tags"]}))
        return

    if args.mode == "replay-case":
        case = json.loads(args.case.read_text(encoding="utf-8"))
        required = {"id", "input", "expected_trajectory", "recorded_tools"}
        missing = sorted(required - set(case)) if isinstance(case, dict) else sorted(required)
        if missing:
            raise ValueError(f"manual case is missing: {', '.join(missing)}")
        tools = RecordedFlowTools(case["recorded_tools"])
        graph = create_graph(
            args.harness,
            tools=tools,
            allow_jira_create=any(item.get("tool") == "jira_create"
                                  for item in case["recorded_tools"]),
        )
        actual = None
        try:
            state = graph.invoke(
                {"request": case["input"]},
                config={"configurable": {"thread_id": f"manual-replay-{case['id']}"}},
            )
            verdict = evaluate_trajectory(state, case["expected_trajectory"])
            actual = capture_actual(state)
        except Exception as exc:
            verdict = {"reward": 0.0, "check_fraction": 0.0,
                       "failure_tags": ["execution_error"], "error": str(exc)[:500]}
        record = {"id": case["id"], "request": case["input"].get("text", ""),
                  "expected_trajectory": case["expected_trajectory"],
                  "actual": actual, "verdict": verdict}
        write_reports([record], json_path=args.report_json, html_path=args.report_html)
        print(json.dumps(verdict, indent=2))
        if verdict["failure_tags"]:
            raise SystemExit(1)
        return

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    graph = create_graph(args.harness, tools=DryRunTools(), allow_jira_create=True)
    verdicts = []
    records = []
    for case in cases:
        actual = None
        try:
            state = graph.invoke({"request": case["input"]},
                                 config={"configurable": {"thread_id": f"trajectory-{case['id']}"}})
            verdict = evaluate_trajectory(state, case["expected_trajectory"])
            actual = capture_actual(state)
        except Exception as exc:
            verdict = {"reward": 0.0, "check_fraction": 0.0,
                       "failure_tags": ["execution_error"], "error": str(exc)[:500]}
        verdicts.append({"id": case["id"], **verdict})
        records.append({"id": case["id"], "request": case["input"].get("text", ""),
                        "expected_trajectory": case["expected_trajectory"],
                        "actual": actual, "verdict": verdict})
    write_reports(records, json_path=args.report_json, html_path=args.report_html)
    print(json.dumps(verdicts, indent=2))
    if any(item["failure_tags"] for item in verdicts):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
