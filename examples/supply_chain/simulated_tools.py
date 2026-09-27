"""Complete, delayed tool responses for an interactive local OCA demo."""

from __future__ import annotations

import time
from typing import Any, Callable

from .fixtures import RecordedTools


DEFAULT_DELAYS = {
    "admin_lookup": 0.7,
    "splunk_search": 1.2,
    "jira_search": 0.8,
    "jira_create": 0.9,
    "github_recent_commits": 0.6,
    "github_pr_files": 1.0,
    "github_compare": 1.1,
    "reproduce_backend": 1.5,
    "reproduce_browser": 1.8,
    "codebot": 2.0,
}


class SimulatedTools(RecordedTools):
    """Use recorded evidence where available and simulated results for every other tool.

    All results are marked simulated. Codebot never applies a patch, Jira never
    creates a real issue, and the delays happen outside the call-recording lock
    so workers in one dispatch wave can run concurrently.
    """

    def __init__(self, *, delay_scale: float = 1.0,
                 sleep: Callable[[float], None] = time.sleep):
        super().__init__()
        if not 0 <= delay_scale <= 10:
            raise ValueError("delay_scale must be between 0 and 10")
        self.delay_scale = delay_scale
        self.sleep = sleep

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in DEFAULT_DELAYS:
            return {"status": "error", "simulated": True, "error": f"unknown tool: {name}"}
        delay = DEFAULT_DELAYS[name] * self.delay_scale
        if delay:
            self.sleep(delay)
        recorded = super().execute(name, arguments)
        if recorded.get("status") == "ok":
            if name == "reproduce_backend":
                recorded = {**recorded, "data": {**recorded["data"],
                            "execution_scope": "Synthetic FastAPI fixture; no Northstar repository checkout"}}
            return {**recorded, "simulated": True, "delay_seconds": delay,
                    "simulation_notice": "Recorded fixture data; not a production tool call"}

        repository = arguments.get("repository", "northstar/inventory-ledger")
        account_id = arguments.get("account_id", "acct-demo")
        if name == "admin_lookup":
            data = {"account_id": account_id, "warehouse": "WH-CLE", "sku": "RM-AL-6061",
                    "warehouse_physical_remaining": 80, "inventory_available": 80,
                    "note": "Simulated account snapshot"}
        elif name == "splunk_search":
            data = {"account_id": account_id, "events": [{"type": "MaterialIssued",
                    "event_id": "evt-mock-001", "delivery_id": "delivery-mock-1"}],
                    "note": "Simulated observability result"}
        elif name == "jira_search":
            data = {"issues": [{"key": "SCM-MOCK-1", "summary": "Simulated material issue history",
                               "status": "Resolved", "url": "https://jira.example/browse/SCM-MOCK-1"}]}
        elif name == "jira_create":
            data = {"key": "SCM-MOCK-NEW", "summary": arguments.get("summary", "Demo investigation"),
                    "created": False, "note": "Simulated ticket; no Jira write occurred"}
        elif name == "github_recent_commits":
            data = [{"sha": "mock-commit-001", "message": "Simulated recent change",
                     "url": f"https://github.example/{repository}/commit/mock-commit-001"}]
        elif name == "github_pr_files":
            data = [{"filename": "src/inventory/material_issue_consumer.py", "status": "modified",
                     "patch": "- dedupe_key = event.event_id\n+ dedupe_key = event.request_id",
                     "url": f"https://github.example/{repository}/pull/{arguments.get('pr_number', 42)}/files"}]
        elif name == "github_compare":
            data = {"comparison_url": f"https://github.example/{repository}/compare/mock",
                    "files": [{"filename": "src/inventory/material_issue_consumer.py", "status": "modified",
                               "patch": "Simulated diff", "url": f"https://github.example/{repository}/blob/mock"}],
                    "commits": [{"sha": "mock-commit-001", "message": "Simulated release change"}]}
        elif name == "reproduce_backend":
            data = {"repository": repository, "scenario": arguments.get("scenario", "material_issue"),
                    "reproduced": True, "note": "Simulated backend replay; no app was started"}
        elif name == "reproduce_browser":
            data = {"repository": repository, "scenario": arguments.get("scenario", "handheld_material_issue"),
                    "steps": ["Open assigned picks", "Scan lot", "Confirm issue", "Check readiness"],
                    "observed": "Simulated confirmation and readiness screens",
                    "note": "No browser was launched"}
        else:  # codebot
            data = {"repository": repository, "analysis": "Simulated code analysis only",
                    "proposed_changes": [arguments.get("task", "Review the selected code path")],
                    "applied": False, "tests_run": False,
                    "note": "No repository checkout, patch, or PR was created"}
        return {"status": "ok", "data": data, "simulated": True, "delay_seconds": delay,
                "simulation_notice": "Generated demo data; not a production tool call"}
