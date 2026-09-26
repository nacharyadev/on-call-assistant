"""Graph state and parallel worker payloads."""
from __future__ import annotations
import operator
from typing import Annotated, Any, TypedDict

class OCAState(TypedDict, total=False):
    request: dict[str, Any]
    capability: str
    blocked: str
    classification: dict[str, Any]
    plan: dict[str, Any]
    context: dict[str, Any]
    tasks: list[dict[str, Any]]
    results: Annotated[list[dict[str, Any]], operator.add]
    answer: dict[str, Any]
    policy_tokens: Annotated[int, operator.add]
    trace: Annotated[list[dict[str, Any]], operator.add]


class WorkerState(TypedDict):
    task: dict[str, Any]
    request: dict[str, Any]
    context: dict[str, Any]
    prior_results: list[dict[str, Any]]
