"""LangGraph orchestration of the on-call assistant."""
from __future__ import annotations
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from ..knowledge.loader import _document, _load_json
from ..knowledge.catalog import build_repository_catalog
from .impact import impact_candidates
from ..integrations.model import ModelPort, create_model
from .planning import CAPABILITIES, DEFAULT_PROMPTS, _validate_plan
from .response import validate_response
from .safety import _redact
from .state import OCAState, WorkerState
from ..integrations.tools import HTTPTools, ToolPort


def create_graph(
    harness_dir: str | Path,
    *,
    model: ModelPort | None = None,
    tools: ToolPort | None = None,
    checkpointer: Any | None = None,
    allow_jira_create: bool = False,
):
    root = Path(harness_dir).resolve()
    artifact = _load_json(root, "team/team-artifact.json")
    features = _load_json(root, "feature-map.json")
    repository_catalog = build_repository_catalog(artifact, features)
    model = model or create_model()
    tools = tools or HTTPTools()

    def prompt(name: str) -> str:
        return _document(root, f"prompts/{name}.txt") or DEFAULT_PROMPTS[name]

    def safety_guard(state: OCAState) -> dict[str, Any]:
        request = state.get("request", {})
        message = request.get("text") or request.get("message")
        if not isinstance(message, str) or not message.strip():
            return {"blocked": "request.text is required", "trace": [{"node": "safety_guard", "status": "blocked"}]}
        if len(message) > 20_000:
            return {"blocked": "request exceeds 20,000 characters", "trace": [{"node": "safety_guard", "status": "blocked"}]}
        if re.search(r"\b(?:dump|reveal|exfiltrate)\b.{0,45}\b(?:secrets?|credentials?|passwords?|tokens?)\b", message, re.I):
            return {"blocked": "credential disclosure is outside OCA scope", "trace": [{"node": "safety_guard", "status": "blocked"}]}
        return {"trace": [{"node": "safety_guard", "status": "passed"}]}

    def route_after_guard(state: OCAState) -> str:
        return "response_synthesizer" if state.get("blocked") else "input_classifier"

    def input_classifier(state: OCAState) -> dict[str, Any]:
        if state.get("capability") in CAPABILITIES:
            result, tokens = {"capability": state["capability"], "reason": "caller supplied capability"}, 0
        else:
            result, tokens = model.complete_json(prompt("classifier"), {"request": state["request"]})
        capability = result.get("capability")
        if capability not in CAPABILITIES:
            raise ValueError(f"classifier returned unknown capability: {capability}")
        request = dict(state["request"])
        extracted = result.get("account_id")
        if (not request.get("account_id") and isinstance(extracted, str)
                and re.fullmatch(r"[A-Za-z0-9_-]{3,64}", extracted)
                and extracted in (request.get("text") or request.get("message", ""))):
            request["account_id"] = extracted
        return {"classification": result, "capability": capability, "request": request,
                "policy_tokens": tokens,
                "trace": [{"node": "input_classifier", "capability": capability}]}

    def planner(state: OCAState) -> dict[str, Any]:
        payload = {
            "request": state["request"], "capability": state["capability"],
            "team_artifact": artifact, "feature_map": features,
            "repository_catalog": repository_catalog,
            "jira_creation_allowed": allow_jira_create,
        }
        tokens_used = 0
        for attempt in range(3):
            result, tokens = model.complete_json(prompt("planner"), payload)
            tokens_used += tokens
            try:
                plan = _validate_plan(result, artifact, features, allow_jira_create,
                                      state["request"].get("account_id"),
                                      state["request"].get("text") or state["request"].get("message", ""),
                                      state["capability"])
                break
            except ValueError as exc:
                if attempt == 2:
                    raise ValueError(f"planner failed validation after 3 attempts: {exc}") from exc
                payload = {**payload, "previous_plan": result, "validation_error": str(exc),
                           "repair_instruction": "Return a complete corrected plan using only the exact allowed tool names and argument keys in the system instructions."}
        return {"plan": plan, "tasks": plan["tasks"], "policy_tokens": tokens_used,
                "trace": [{"node": "planner", "task_count": len(plan["tasks"]),
                           "repositories": plan["repositories"], "attempts": attempt + 1}]}

    def context_synthesizer(state: OCAState) -> dict[str, Any]:
        documents = {path: content for path in state["plan"]["document_paths"]
                     if (content := _document(root, path))}
        selected_domains = [item for item in artifact.get("domains", [])
                            if item.get("id") in state["plan"]["domain_ids"]]
        selected_features = [item for item in features.get("features", [])
                             if item.get("name") in state["plan"]["feature_names"]]
        context = {"domains": selected_domains, "features": selected_features,
                   "repositories": state["plan"]["repositories"],
                   "focus_repositories": state["plan"]["focus_repositories"],
                   "repository_catalog": {name: repository_catalog[name] for name in state["plan"]["repositories"]},
                   "documents": documents}
        return {"context": context, "trace": [{"node": "context_synthesizer", "document_count": len(documents)}]}

    def dispatch(state: OCAState) -> dict[str, Any]:
        by_id = {task["id"]: task for task in state["tasks"]}
        ready = [task["id"] for task in state["tasks"] if task["status"] == "pending"
                 and all(by_id[dep]["status"] == "completed" for dep in task["depends_on"])]
        if ready:
            now = datetime.now(timezone.utc).isoformat()
            tasks = [{**task, "status": "running", "started_at": now}
                     if task["id"] in ready else task for task in state["tasks"]]
            return {"tasks": tasks, "trace": [{"node": "dispatch", "ready": ready}]}
        return {"trace": [{"node": "dispatch", "ready": []}]}

    def route_dispatch(state: OCAState):
        completed = {result["task_id"]: result for result in state.get("results", [])}
        ready = [task for task in state["tasks"] if task["status"] == "running"
                 and task["id"] not in completed]
        if ready:
            return [Send("worker", {"task": task, "request": state["request"], "context": state["context"],
                                    "prior_results": [completed[dep] for dep in task["depends_on"]]})
                    for task in ready]
        return "response_synthesizer"

    def worker(state: WorkerState) -> dict[str, Any]:
        task = state["task"]
        arguments = dict(task["arguments"])
        if task["tool"] in {"codebot", "reproduce_backend", "reproduce_browser"}:
            arguments.update({"request": state["request"], "context": state["context"],
                              "prior_results": state["prior_results"]})
        try:
            outcome = _redact(tools.execute(task["tool"], arguments))
        except Exception as exc:
            outcome = {"status": "error", "error": str(exc)}
        if not isinstance(outcome, dict):
            outcome = {"status": "error", "error": "tool returned a non-object result"}
        return {"results": [{"task_id": task["id"], "tool": task["tool"], "outcome": outcome}],
                "policy_tokens": int(outcome.get("policy_tokens", 0) or 0),
                "trace": [{"node": "worker", "task_id": task["id"], "tool": task["tool"],
                           "status": outcome.get("status", "error")}]}

    def merge(state: OCAState) -> dict[str, Any]:
        outcomes = {result["task_id"]: result["outcome"] for result in state.get("results", [])}
        tasks = []
        for task in state["tasks"]:
            updated = dict(task)
            if task["id"] in outcomes:
                updated["status"] = "completed" if outcomes[task["id"]].get("status") == "ok" else outcomes[task["id"]].get("status", "error")
                updated["finished_at"] = datetime.now(timezone.utc).isoformat()
            tasks.append(updated)
        # A failed prerequisite blocks its dependents, including transitive ones.
        by_id = {task["id"]: task for task in tasks}
        changed = True
        while changed:
            changed = False
            for task in tasks:
                if task["status"] == "pending" and any(by_id[dep]["status"] not in {"pending", "completed"} for dep in task["depends_on"]):
                    task["status"] = "blocked"
                    task["finished_at"] = datetime.now(timezone.utc).isoformat()
                    changed = True
        return {"tasks": tasks, "trace": [{"node": "merge", "statuses": {task["id"]: task["status"] for task in tasks}}]}

    def response_synthesizer(state: OCAState) -> dict[str, Any]:
        if state.get("blocked"):
            return {"answer": {"summary": state["blocked"], "findings": [], "evidence": [],
                               "remaining_work": [], "task_status": {}},
                    "trace": [{"node": "response_synthesizer", "status": "blocked"}]}
        payload = {
            "request": state["request"], "capability": state["capability"],
            "plan": state["plan"], "context": state["context"],
            "feature_map": features if state["capability"] == "release_impact" else None,
            "impact_candidates": impact_candidates(state["tasks"], state.get("results", []), features)
            if state["capability"] == "release_impact" else [],
            "tasks": state["tasks"], "results": state.get("results", []),
        }
        tokens_used = 0
        for attempt in range(3):
            result, tokens = model.complete_json(prompt("response"), payload)
            tokens_used += tokens
            try:
                result = validate_response(result, state["tasks"], state["capability"])
                break
            except ValueError as exc:
                if attempt == 2:
                    raise ValueError(f"response failed validation after 3 attempts: {exc}") from exc
                payload = {**payload, "previous_response": result, "validation_error": str(exc),
                           "repair_instruction": "Return only the requested answer fields, citing actual task IDs. Do not echo tasks or results."}
        result["task_status"] = {task["id"]: task["status"] for task in state["tasks"]}
        result["incomplete_tasks"] = [
            {"id": task["id"], "tool": task["tool"], "status": task["status"]}
            for task in state["tasks"] if task["status"] != "completed"
        ]
        result["routing"] = {
            "domains": state["plan"]["domain_ids"],
            "features": state["plan"]["feature_names"],
            "repositories": state["plan"]["repositories"],
            "focus_repositories": state["plan"]["focus_repositories"],
        }
        return {"answer": result, "policy_tokens": tokens_used,
                "trace": [{"node": "response_synthesizer", "status": "completed"}]}

    graph = StateGraph(OCAState)
    for name, node in (("safety_guard", safety_guard), ("input_classifier", input_classifier),
                       ("planner", planner), ("context_synthesizer", context_synthesizer),
                       ("dispatch", dispatch), ("worker", worker), ("merge", merge),
                       ("response_synthesizer", response_synthesizer)):
        graph.add_node(name, node)
    graph.add_edge(START, "safety_guard")
    graph.add_conditional_edges("safety_guard", route_after_guard)
    graph.add_edge("input_classifier", "planner")
    graph.add_edge("planner", "context_synthesizer")
    graph.add_edge("context_synthesizer", "dispatch")
    graph.add_conditional_edges("dispatch", route_dispatch)
    graph.add_edge("worker", "merge")
    graph.add_edge("merge", "dispatch")
    graph.add_edge("response_synthesizer", END)
    return graph.compile(checkpointer=checkpointer or InMemorySaver())
