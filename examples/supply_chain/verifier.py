"""Outcome checks independent of the demo model's plan and summary."""

from __future__ import annotations

import json
from typing import Any

from on_call_assistant.agent.impact import impact_candidates

from .fixtures import FEATURE, INVENTORY_REPO, MANUFACTURING_REPO, WAREHOUSE_REPO, ROOT, RecordedTools


def _states_tentative_impact(summary: str) -> bool:
    wording = summary.lower()
    return any(term in wording for term in
               ("candidate", "plausib", "potential", "not a confirmed", "not proven", "unverified"))


def verify_outcome(case: dict[str, Any], state: dict[str, Any], tools: RecordedTools) -> dict[str, Any]:
    expected = case["expected_outcome"]
    tasks = {item["id"]: item for item in state.get("tasks", [])}
    results = state.get("results", [])

    def outcome_for(tool: str, repository: str | None = None) -> dict[str, Any]:
        for item in results:
            task = tasks.get(item.get("task_id"), {})
            if item.get("tool") == tool and (repository is None or
                                             task.get("arguments", {}).get("repository") == repository):
                return item.get("outcome", {})
        return {}

    answer = state.get("answer", {})
    checks: dict[str, bool] = {}

    def check(name: str, condition: bool) -> None:
        checks[name] = bool(condition)

    check("design_context_loaded", "decisions/adr-014-material-issue-idempotency.md"
          in state.get("context", {}).get("documents", {}))
    check("codebot_unfinished", any(item.get("tool") == "codebot" and item.get("status") == "stub"
                                    for item in answer.get("incomplete_tasks", [])))

    if case["id"] == "account-material-issue":
        admin = outcome_for("admin_lookup").get("data", {})
        logs = outcome_for("splunk_search").get("data", {})
        replay = outcome_for("reproduce_backend").get("data", {})
        commits = outcome_for("github_recent_commits", INVENTORY_REPO).get("data", [])
        issues = outcome_for("jira_search").get("data", {}).get("issues", [])
        observed = replay.get("observed", {})
        reference = replay.get("reference_event_id_dedupe", {})
        check("account_stock_discrepancy", admin.get("warehouse_physical_remaining") == expected["warehouse_physical_remaining"]
              and admin.get("inventory_available") == expected["incorrect_inventory_available"])
        check("same_event_two_deliveries", logs.get("event_id") == expected["event_id"]
              and len(logs.get("deliveries", [])) == 2
              and len({item["delivery_id"] for item in logs.get("deliveries", [])}) == 2)
        check("backend_reproduced", replay.get("bug_reproduced") is True
              and replay.get("initial_quantity") == expected["initial_quantity"]
              and replay.get("issue_quantity") == expected["issue_quantity"]
              and observed.get("retry", {}).get("inventory_available") == expected["incorrect_inventory_available"]
              and observed.get("retry", {}).get("warehouse_physical") == expected["warehouse_physical_remaining"]
              and observed.get("work_order_http_status") == 409)
        check("reference_contract", reference.get("retry", {}).get("inventory_available")
              == expected["correct_inventory_available"] and reference.get("work_order_http_status") == 200)
        check("change_and_history_evidence", any(item.get("sha") == expected["suspect_commit"] for item in commits)
              and any(item.get("key") == expected["prior_issue"] for item in issues))
        claims = " ".join([answer.get("summary", ""), answer.get("root_cause_hypothesis", "")]
                          + [item.get("claim", "") for item in answer.get("findings", [])]).lower()
        check("grounded_response", all(term in claims for term in
              (expected["event_id"].lower(), expected["blocked_work_order"].lower(),
               expected["suspect_commit"].lower(), expected["prior_issue"].lower(),
               "request_id", "event_id")))
        codebot_calls = [args for name, args in tools.calls if name == "codebot"]
        check("codebot_received_evidence", len(codebot_calls) == 1
              and {item["tool"] for item in codebot_calls[0].get("prior_results", [])}
              >= {"splunk_search", "jira_search", "github_recent_commits", "reproduce_backend"}
              and "decisions/adr-014-material-issue-idempotency.md"
              in codebot_calls[0].get("context", {}).get("documents", {}))
    elif case["id"] == "release-material-issue":
        compares = [item for item in state.get("results", []) if item.get("tool") == "github_compare"]
        check("three_repository_diffs", len(compares) == 3
              and all(item["outcome"].get("status") == "ok" for item in compares))
        feature_map = json.loads((ROOT / "harness" / "feature-map.json").read_text(encoding="utf-8"))
        candidates = impact_candidates(state["tasks"], state.get("results", []), feature_map)
        matched_repositories = {item["repository"] for item in candidates
                                if item["feature"] == FEATURE and item["match"] == "path"}
        check("path_matched_impact", matched_repositories == set(expected["changed_repositories"])
              == {INVENTORY_REPO, WAREHOUSE_REPO, MANUFACTURING_REPO})
        check("affected_feature_reported", expected["affected_feature"] in answer.get("affected_features", []))
        check("owner_consumer_test_reported", expected["required_owner"] in answer.get("owners", [])
              and expected["required_consumer"] in answer.get("consumers", [])
              and expected["required_test"] in answer.get("tests", []))
        check("impact_stated_as_candidate", _states_tentative_impact(answer.get("summary", "")))
    else:
        check("known_case", False)

    failures = [name for name, passed in checks.items() if not passed]
    return {"passed": not failures, "checks": checks, "failure_tags": failures}
