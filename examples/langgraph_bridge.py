"""Runner bridge for a LangGraph agent supplied by another codebase.

Set ONCALL_GRAPH_FACTORY=package.module:factory. The factory accepts the harness
directory path and returns a compiled graph. Adapt graph input/output here to
the actual on-call agent's state schema.
"""

import importlib
import json
import os
import sys


def main() -> None:
    request = json.load(sys.stdin)
    reference = os.environ["ONCALL_GRAPH_FACTORY"]
    module_name, factory_name = reference.split(":", 1)
    factory = getattr(importlib.import_module(module_name), factory_name)
    graph = factory(request["harness_dir"])
    task_input = dict(request["task"]["input"])
    if "text" not in task_input and "request" in task_input:
        task_input["text"] = task_input["request"]
    state = graph.invoke(
        {"request": task_input},
        config={"configurable": {"thread_id": f"rrsi-{request['task']['id']}-{request['seed']}",
                                 "harness_dir": request["harness_dir"]}},
    )
    # The graph must return metered usage; counting only the last LLM call is wrong.
    print(json.dumps({"answer": state["answer"], "capability": state.get("capability"),
                      "policy_tokens": state["policy_tokens"],
                      "trace": state.get("trace", []), "tasks": state.get("tasks", []),
                      "plan": state.get("plan", {})}))


if __name__ == "__main__":
    main()
