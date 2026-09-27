"""RRSI runner for the actual LangGraph agent with isolated tool stubs."""

from __future__ import annotations

import json
import sys

from ..agent.graph import create_graph
from .dry_run import DryRunTools
from .captured_flows import RecordedFlowTools


def run_trial(payload: dict) -> dict:
    task = payload["task"]
    tools = (RecordedFlowTools(task["recorded_tools"]) if "recorded_tools" in task
             else DryRunTools())
    graph = create_graph(payload["harness_dir"], tools=tools,
                         allow_jira_create=any(item["tool"] == "jira_create"
                                               for item in task.get("recorded_tools", [])))
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
        "results": state.get("results", []),
        "plan": state.get("plan", {}),
    }


def main() -> None:
    print(json.dumps(run_trial(json.load(sys.stdin))))


if __name__ == "__main__":
    main()
