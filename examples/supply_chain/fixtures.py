"""Recorded tool responses and a deterministic model for the supply-chain replay.

The deterministic model is a wiring fixture. Use the same cases with a real model
to evaluate classifier, planner, and synthesis quality.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

from .mini_services import ACCOUNT, EVENT_ID, replay_material_issue


ROOT = Path(__file__).resolve().parent
INVENTORY_REPO = "northstar/inventory-ledger"
WAREHOUSE_REPO = "northstar/warehouse-execution"
MANUFACTURING_REPO = "northstar/manufacturing-execution"
FEATURE = "material issue and production consumption"
DOMAINS = ["inventory", "warehouse", "manufacturing"]


class RecordedTools:
    def __init__(self, records: dict[str, Any] | None = None):
        self.records = records or json.loads((ROOT / "recorded_tools.json").read_text(encoding="utf-8"))
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._lock = Lock()

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.calls.append((name, arguments))
        if name in {"admin_lookup", "splunk_search"} and arguments.get("account_id") != ACCOUNT:
            return {"status": "error", "error": "unknown fixture account"}
        if name == "reproduce_backend":
            prior = {item["tool"] for item in arguments.get("prior_results", [])}
            if arguments.get("repository") != INVENTORY_REPO or not {"admin_lookup", "splunk_search"} <= prior:
                return {"status": "error", "error": "replay requires account snapshot and logs"}
            return {"status": "ok", "data": replay_material_issue()}
        if name == "codebot":
            return {"status": "stub", "message": "Codebot is intentionally not connected in this example"}
        if name == "github_recent_commits":
            data = self.records[name].get(arguments.get("repository"))
        elif name == "github_compare":
            if (arguments.get("base"), arguments.get("head")) != ("v3.7.0", "v3.8.0"):
                return {"status": "error", "error": "unknown fixture release refs"}
            data = self.records[name].get(arguments.get("repository"))
        else:
            data = self.records.get(name)
        if data is None:
            return {"status": "unavailable", "reason": f"no fixture for {name}"}
        return {"status": "ok", "data": data}


class FixtureModel:
    """Public-request-driven playbook; it never reads expected eval fields."""

    def complete_json(self, system: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        if "results" in payload:
            return self._synthesize(payload), 41
        if "team_artifact" in payload:
            return self._plan(payload), 67
        request = payload["request"]
        is_release = "compare" in request["text"].lower() and "v3.8.0" in request["text"]
        return {"capability": "release_impact" if is_release else "bug_analysis",
                "reason": "version comparison" if is_release else "account-scoped stock discrepancy",
                "account_id": request.get("account_id")}, 19

    def _plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = payload["request"]
        if payload["capability"] == "release_impact":
            compares = [
                {"id": f"compare_{index}", "tool": "github_compare",
                 "arguments": {"repository": repo, "base": "v3.7.0", "head": "v3.8.0"},
                 "depends_on": []}
                for index, repo in enumerate((INVENTORY_REPO, WAREHOUSE_REPO, MANUFACTURING_REPO), 1)
            ]
            tasks = compares + [{
                "id": "code_analysis", "tool": "codebot",
                "arguments": {"repository": INVENTORY_REPO,
                              "task": "Inspect changed material-issue contracts and downstream callers"},
                "depends_on": [item["id"] for item in compares],
            }]
        else:
            account_id = request.get("account_id", ACCOUNT)
            tasks = [
                {"id": "account", "tool": "admin_lookup", "arguments": {"account_id": account_id}, "depends_on": []},
                {"id": "logs", "tool": "splunk_search", "arguments": {"account_id": account_id,
                  "query": "evt-mi-7842 OR WO-4822"}, "depends_on": []},
                {"id": "history", "tool": "jira_search", "arguments": {"query": "duplicate material issue scanner retry"}, "depends_on": []},
                {"id": "commits", "tool": "github_recent_commits", "arguments": {"repository": INVENTORY_REPO}, "depends_on": []},
                {"id": "repro", "tool": "reproduce_backend", "arguments": {"repository": INVENTORY_REPO,
                  "scenario": "duplicate_material_issue"}, "depends_on": ["account", "logs"]},
                {"id": "code_analysis", "tool": "codebot", "arguments": {"repository": INVENTORY_REPO,
                  "task": "Trace the dedupe key regression and propose a patch with an idempotency test"},
                 "depends_on": ["logs", "history", "commits", "repro"]},
            ]
        return {"domain_ids": DOMAINS, "feature_names": [FEATURE], "tasks": tasks,
                "rationale": "Follow the material-issue event across all three owning domains"}

    def _synthesize(self, payload: dict[str, Any]) -> dict[str, Any]:
        outcomes = {item["task_id"]: item["outcome"] for item in payload["results"]}
        if payload["capability"] == "release_impact":
            candidates = payload.get("impact_candidates", [])
            return {
                "summary": "The v3.8.0 diff touches the material-issue path in inventory, warehouse, and manufacturing; these are candidate impacts, not proven regressions.",
                "findings": [{"claim": "Material-issue contracts and work-order checks changed",
                              "evidence_tasks": ["compare_1", "compare_2", "compare_3"]}],
                "evidence": [{"task_id": item["evidence_task_id"], "url": item.get("url")}
                             for item in candidates],
                "affected_features": sorted({item["feature"] for item in candidates}),
                "owners": sorted({owner for item in candidates for owner in item["owners"]}),
                "consumers": sorted({consumer for item in candidates for consumer in item["consumers"]}),
                "tests": sorted({test for item in candidates for test in item["tests"]}),
                "remaining_work": ["Codebot is a stub; confirm caller-level behavior before release"],
            }

        needed = {"account", "logs", "history", "commits", "repro"}
        if not needed <= outcomes.keys() or any(outcomes[key].get("status") != "ok" for key in needed):
            return {"summary": "Investigation lacks required evidence", "findings": [],
                    "evidence": [], "remaining_work": ["Resolve failed evidence tasks"]}
        account = outcomes["account"]["data"]
        logs = outcomes["logs"]["data"]
        replay = outcomes["repro"]["data"]
        commits = outcomes["commits"]["data"]
        issue = outcomes["history"]["data"]["issues"][0]
        duplicate = len({item["delivery_id"] for item in logs["deliveries"]}) == 2
        reproduced = replay["bug_reproduced"] and duplicate
        summary = (f"Material issue {logs['event_id']} was delivered twice. Inventory availability fell to "
                   f"{account['inventory_available']} while the warehouse retained "
                   f"{account['warehouse_physical_remaining']} physical units, blocking "
                   f"{account['blocked_work_order']}.") if reproduced else "The stock discrepancy needs more evidence."
        return {
            "summary": summary,
            "findings": [
                {"claim": "Duplicate delivery applied the 80-unit issue twice in inventory; the backend replay reproduces the blocked work order.",
                 "evidence_tasks": ["account", "logs", "repro"]},
                {"claim": f"Commit {commits[0]['sha']} changed the dedupe key to optional request_id; this is a likely regression, pending code review.",
                 "evidence_tasks": ["commits", "logs", "repro"]},
                {"claim": f"Prior incident {issue['key']} describes a similar retry path.",
                 "evidence_tasks": ["history"]},
            ],
            "evidence": [{"task_id": "history", "url": issue["url"]},
                         {"task_id": "commits", "url": commits[0]["url"]},
                         {"task_id": "repro", "event_id": logs["event_id"]}],
            "reproduction": {"event_id": replay["event_id"],
                             "warehouse_physical_remaining": replay["observed"]["retry"]["warehouse_physical"],
                             "observed_inventory_available": replay["observed"]["retry"]["inventory_available"],
                             "expected_inventory_available": replay["reference_event_id_dedupe"]["retry"]["inventory_available"],
                             "work_order_http_status": replay["observed"]["work_order_http_status"]},
            "root_cause_hypothesis": "The consumer deduplicates by optional request_id instead of stable event_id.",
            "remaining_work": ["Codebot is a stub; patch and regression test remain pending"],
        }
