"""Constrained model-backed proposer and critic for the live smoke demo."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..integrations.model import OpenAIModel


PLANNER_PATH = "prompts/planner.txt"


def propose(payload: dict[str, Any], model: OpenAIModel) -> dict[str, Any]:
    current = (Path(payload["incumbent_harness_dir"]) / PLANNER_PATH).read_text(encoding="utf-8")
    result, _ = model.complete_json(
        "You improve a reusable on-call agent planner prompt. Return JSON with "
        "replacement_prompt (the entire revised prompt) and hypothesis. Make one small, "
        "generalizable change based on aggregate failures. Do not encode task IDs, answers, "
        "or benchmark-specific strings. Preserve JSON output and tool-routing requirements. "
        "If there is no credible improvement, return {\"replacement_prompt\": \"\", \"hypothesis\": \"\"}.",
        {
            "current_prompt": current,
            "feedback": payload["feedback"],
            "recent_history": payload.get("history", [])[-5:],
            "edit_budget": payload["edit_budget"],
        },
    )
    revised = result.get("replacement_prompt")
    hypothesis = result.get("hypothesis")
    if not isinstance(revised, str) or not isinstance(hypothesis, str):
        raise ValueError("proposer must return string replacement_prompt and hypothesis")
    if not revised.strip() or revised.strip() == current.strip():
        return {"candidates": []}
    if not hypothesis.strip() or len(revised.encode("utf-8")) > 20_000:
        raise ValueError("proposer returned an empty hypothesis or an oversized prompt")
    return {"candidates": [{"edits": [{
        "component": "prompt",
        "hypothesis": hypothesis[:500],
        "path": PLANNER_PATH,
        "operation": "replace",
        "content": revised.rstrip() + "\n",
    }]}]}


def critique(payload: dict[str, Any], model: OpenAIModel) -> dict[str, Any]:
    edits = payload["edits"]
    if len(edits) != 1 or edits[0].get("path") != PLANNER_PATH or edits[0].get("component") != "prompt":
        return {"approved": False, "reason": "live demo only allows one planner prompt edit"}
    result, _ = model.complete_json(
        "Review a proposed agent prompt diff for benchmark leakage and generality. "
        "Reject task-ID memorization, hardcoded outputs, removal of safety constraints, "
        "or instructions that claim dry-run tool responses are real evidence. "
        "Return JSON with approved (boolean) and reason (short string).",
        {
            "diff": payload["diff"],
            "evolve_task_ids": payload.get("evolve_task_ids", []),
            "forbidden_terms": payload.get("forbidden_terms", []),
        },
    )
    return {"approved": result.get("approved") is True,
            "reason": str(result.get("reason", "critic did not approve"))[:500]}


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"propose", "critic"}:
        raise SystemExit("usage: python -m on_call_assistant.evolution.model_adapters propose|critic")
    payload = json.load(sys.stdin)
    model = OpenAIModel()
    result = propose(payload, model) if sys.argv[1] == "propose" else critique(payload, model)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
