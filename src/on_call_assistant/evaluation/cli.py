"""Run a dry-run pathway suite or verify an RRSI trial from stdin."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..agent.graph import create_graph
from .dry_run import DryRunTools
from .trajectory import evaluate_trajectory


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate OCA's workflow trajectory")
    subparsers = parser.add_subparsers(dest="mode", required=True)
    subparsers.add_parser("verify-rrsi", help="read an RRSI verifier request from stdin")
    suite = subparsers.add_parser("run-suite", help="run pathway cases with mocked tools")
    suite.add_argument("cases", type=Path)
    suite.add_argument("--harness", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "verify-rrsi":
        payload = json.load(sys.stdin)
        expectation = payload["task"].get("expected_trajectory", {})
        if not expectation:
            raise ValueError("task needs expected_trajectory")
        verdict = evaluate_trajectory(payload["agent_output"], expectation)
        print(json.dumps({"reward": verdict["reward"], "failure_tags": verdict["failure_tags"]}))
        return

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    graph = create_graph(args.harness, tools=DryRunTools(), allow_jira_create=True)
    verdicts = []
    for case in cases:
        try:
            state = graph.invoke({"request": case["input"]},
                                 config={"configurable": {"thread_id": f"trajectory-{case['id']}"}})
            verdict = evaluate_trajectory(state, case["expected_trajectory"])
        except Exception as exc:
            verdict = {"reward": 0.0, "check_fraction": 0.0,
                       "failure_tags": ["execution_error"], "error": str(exc)[:500]}
        verdicts.append({"id": case["id"], **verdict})
    print(json.dumps(verdicts, indent=2))
    if any(item["failure_tags"] for item in verdicts):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
