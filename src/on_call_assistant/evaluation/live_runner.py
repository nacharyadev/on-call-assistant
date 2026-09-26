"""RRSI runner for the actual LangGraph agent with isolated tool stubs."""

from __future__ import annotations

import json
import sys

from ..agent.graph import create_graph
from .dry_run import DryRunTools


def run_trial(payload: dict) -> dict:
    task = payload["task"]
    graph = create_graph(payload["harness_dir"], tools=DryRunTools())
    state = graph.invoke(
        {"request": task["input"]},
        config={"configurable": {"thread_id": f"rrsi-{task['id']}-{payload['seed']}"}},
    )
    return {
        "answer": state["answer"],
        "capability": state.get("capability"),
        "policy_tokens": state.get("policy_tokens", 0),
        "trace": state.get("trace", []),
        "tasks": state.get("tasks", []),
        "plan": state.get("plan", {}),
    }


def main() -> None:
    print(json.dumps(run_trial(json.load(sys.stdin))))


if __name__ == "__main__":
    main()
