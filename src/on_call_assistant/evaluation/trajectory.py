"""Evaluate the route an OCA request actually took through the graph."""

from __future__ import annotations

from collections import Counter
from typing import Any


DEFAULT_NODES = [
    "safety_guard", "input_classifier", "planner", "context_synthesizer",
    "dispatch", "worker", "merge", "response_synthesizer",
]


def evaluate_trajectory(output: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    """Score path checks without relying on order among parallel workers.

    Expected fields are intentionally declarative so the same evaluator works
    for standalone suites and hidden RRSI verifier metadata.
    """
    trace = output.get("trace", [])
    tasks = output.get("tasks", [])
    answer = output.get("answer", {})
    routing = answer.get("routing", {}) if isinstance(answer, dict) else {}
    task_by_id = {task.get("id"): task for task in tasks if isinstance(task, dict)}
    observed_nodes = [entry.get("node") for entry in trace if isinstance(entry, dict)]
    observed_tools = [entry.get("tool") for entry in trace
                      if isinstance(entry, dict) and entry.get("node") == "worker"]
    checks: list[dict[str, Any]] = []

    def check(label: str, passed: bool) -> None:
        checks.append({"name": label, "passed": bool(passed)})

    required_nodes = expected.get("required_nodes", DEFAULT_NODES)
    position = -1
    ordered = True
    for node in required_nodes:
        try:
            position = observed_nodes.index(node, position + 1)
        except ValueError:
            ordered = False
            break
    check("node_sequence", ordered)

    if "capability" in expected:
        check("capability", output.get("capability") == expected["capability"])
    for tool in expected.get("required_tools", []):
        check(f"required_tool:{tool}", tool in observed_tools)
    for group in expected.get("any_of_tools", []):
        check("any_of_tools:" + ",".join(group), any(tool in observed_tools for tool in group))
    for tool in expected.get("forbidden_tools", []):
        check(f"forbidden_tool:{tool}", tool not in observed_tools)
    for domain in expected.get("required_domains", []):
        check(f"domain:{domain}", domain in routing.get("domains", []))
    for repo in expected.get("required_repositories", []):
        check(f"repository:{repo}", repo in routing.get("repositories", []))

    for tool, repositories in expected.get("tool_repositories", {}).items():
        actual = {task.get("arguments", {}).get("repository") for task in tasks
                  if task.get("tool") == tool}
        for repo in repositories:
            check(f"tool_repository:{tool}:{repo}", repo in actual)

    dispatch_waves = []
    for entry in trace:
        if isinstance(entry, dict) and entry.get("node") == "dispatch" and entry.get("ready"):
            dispatch_waves.append(set(entry["ready"]))
    for index, group in enumerate(expected.get("parallel_tools", [])):
        check(f"parallel_group:{index}", any(
            not (Counter(group) - Counter(task_by_id[task_id]["tool"]
                                          for task_id in wave if task_id in task_by_id))
            for wave in dispatch_waves))

    for relation in expected.get("dependencies", []):
        before, after = relation["before"], relation["after"]
        before_ids = {task["id"] for task in tasks if task.get("tool") == before}
        check(f"dependency:{before}->{after}", any(
            before_ids.intersection(task.get("depends_on", []))
            for task in tasks if task.get("tool") == after))

    account_id = expected.get("account_id")
    if account_id:
        check("account_lookup", any(
            task.get("tool") in {"admin_lookup", "splunk_search"}
            and task.get("arguments", {}).get("account_id") == account_id
            for task in tasks))
    for tool in expected.get("completed_tools", []):
        check(f"completed_tool:{tool}", any(task.get("tool") == tool and task.get("status") == "completed"
                                                for task in tasks))

    failed = [item["name"] for item in checks if not item["passed"]]
    return {"reward": 1.0 if checks and not failed else 0.0,
            "check_fraction": sum(item["passed"] for item in checks) / len(checks) if checks else 0.0,
            "failure_tags": failed, "checks": checks}
