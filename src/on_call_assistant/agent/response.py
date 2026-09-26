"""Shape and evidence checks for model-written answers."""

from __future__ import annotations

from typing import Any


ANSWER_FIELDS = {
    "summary", "findings", "evidence", "remaining_work", "reproduction",
    "root_cause_hypothesis", "affected_features", "owners", "consumers", "tests",
}


def validate_response(raw: dict[str, Any], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("answer must be a JSON object")
    unexpected = set(raw) - ANSWER_FIELDS
    if unexpected:
        raise ValueError(f"answer contains unsupported fields: {', '.join(sorted(unexpected))}")
    if not isinstance(raw.get("summary"), str) or not raw["summary"].strip():
        raise ValueError("answer needs a nonempty summary")
    ids = {task["id"] for task in tasks}
    findings = raw.get("findings")
    if not isinstance(findings, list):
        raise ValueError("findings must be a list")
    for finding in findings:
        if not isinstance(finding, dict) or not isinstance(finding.get("claim"), str):
            raise ValueError("each finding needs a claim")
        references = finding.get("evidence_tasks", [])
        if not isinstance(references, list) or any(ref not in ids for ref in references):
            raise ValueError("finding cites an unknown task ID")
    evidence = raw.get("evidence")
    if not isinstance(evidence, list):
        raise ValueError("evidence must be a list")
    for item in evidence:
        if not isinstance(item, dict) or item.get("task_id") not in ids:
            raise ValueError("evidence cites an unknown task ID")
    if not isinstance(raw.get("remaining_work"), list):
        raise ValueError("remaining_work must be a list")
    for key in ("affected_features", "owners", "consumers", "tests"):
        if key in raw and (not isinstance(raw[key], list) or not all(isinstance(x, str) for x in raw[key])):
            raise ValueError(f"{key} must be a list of strings")
    return raw
