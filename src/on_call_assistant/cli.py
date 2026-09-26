from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from .agent.graph import create_graph


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the on-call assistant")
    parser.add_argument("text", nargs="?", help="request text; defaults to stdin")
    parser.add_argument("--harness", type=Path, default=Path("examples/agent_harness"))
    parser.add_argument("--account-id")
    parser.add_argument("--allow-jira-create", action="store_true")
    args = parser.parse_args()
    message = args.text or sys.stdin.read()
    request = {"text": message}
    if args.account_id:
        request["account_id"] = args.account_id
    graph = create_graph(args.harness, allow_jira_create=args.allow_jira_create)
    state = graph.invoke({"request": request}, config={"configurable": {"thread_id": str(uuid.uuid4())}})
    print(json.dumps({"answer": state.get("answer"), "tasks": state.get("tasks", []),
                      "policy_tokens": state.get("policy_tokens", 0)}, indent=2))


if __name__ == "__main__":
    main()
