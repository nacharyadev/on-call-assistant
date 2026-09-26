import json
import subprocess
import sys
import tempfile
import time
import threading
import unittest
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from on_call_assistant.agent import create_graph
from on_call_assistant.agent.impact import impact_candidates
from on_call_assistant.agent.planning import _validate_plan
from on_call_assistant.knowledge.catalog import build_repository_catalog
from on_call_assistant.agent.response import validate_response
from on_call_assistant.api.service import create_app
from on_call_assistant.evaluation.trajectory import evaluate_trajectory
from on_call_assistant.integrations.tools import HTTPTools


class FakeModel:
    def __init__(self, plan):
        self.plan = plan
        self.calls = []

    def complete_json(self, system, payload):
        self.calls.append(payload)
        if "team_artifact" in payload:
            return self.plan, 10
        if "results" in payload:
            return {"summary": "investigation complete", "findings": [], "evidence": [], "remaining_work": []}, 5
        return {"capability": "bug_analysis", "reason": "reported issue"}, 3


class FakeTools:
    def __init__(self):
        self.calls = []

    def execute(self, name, arguments):
        self.calls.append((name, arguments))
        return {"status": "ok", "data": {"tool": name, "token": "must be redacted"}}


class OcaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "team").mkdir()
        (self.root / "prds").mkdir()
        (self.root / "prds" / "checkout.md").write_text("Checkout contract")
        (self.root / "team" / "team-artifact.json").write_text(json.dumps({"domains": [
            {"id": "checkout", "repositories": ["org/api", "org/web"], "prd_paths": ["prds/checkout.md"]}]}))
        (self.root / "feature-map.json").write_text(json.dumps({"features": [
            {"name": "submission", "repositories": ["org/api", "org/web"], "ground_truth": ["prds/checkout.md"]}]}))

    def plan(self):
        return {"domain_ids": ["checkout"], "feature_names": ["submission"], "tasks": [
            {"id": "history", "tool": "github_recent_commits", "arguments": {"repository": "org/api"}, "depends_on": []},
            {"id": "tickets", "tool": "jira_search", "arguments": {"query": "checkout"}, "depends_on": []},
            {"id": "analysis", "tool": "codebot", "arguments": {"repository": "org/web", "task": "inspect failure"},
             "depends_on": ["history", "tickets"]},
        ]}

    def test_parallel_wave_merge_and_persisted_task_list(self):
        model, tools = FakeModel(self.plan()), FakeTools()
        graph = create_graph(self.root, model=model, tools=tools)
        config = {"configurable": {"thread_id": "request-1"}}
        output = graph.invoke({"request": {"text": "Checkout fails for some customers"}}, config=config)
        self.assertEqual({task["id"]: task["status"] for task in output["tasks"]},
                         {"history": "completed", "tickets": "completed", "analysis": "completed"})
        self.assertEqual(output["policy_tokens"], 18)
        self.assertEqual({name for name, _ in tools.calls[:2]}, {"github_recent_commits", "jira_search"})
        self.assertEqual(tools.calls[2][0], "codebot")
        self.assertEqual(graph.get_state(config).values["tasks"], output["tasks"])
        self.assertEqual(output["results"][0]["outcome"]["data"]["token"], "[REDACTED]")
        self.assertEqual(output["answer"]["task_status"]["analysis"], "completed")
        self.assertEqual(output["answer"]["routing"]["repositories"], ["org/api", "org/web"])

    def test_planner_repairs_invalid_model_tool_without_running_it(self):
        class RepairingModel(FakeModel):
            def complete_json(self, system, payload):
                if "team_artifact" in payload and "validation_error" not in payload:
                    self.calls.append(payload)
                    invalid = {**self.plan, "tasks": [{"id": "bad", "tool": "git", "arguments": {},
                                                        "depends_on": []}]}
                    return invalid, 7
                return super().complete_json(system, payload)

        model, tools = RepairingModel(self.plan()), FakeTools()
        output = create_graph(self.root, model=model, tools=tools).invoke(
            {"request": {"text": "Checkout fails"}},
            config={"configurable": {"thread_id": "repair"}})
        self.assertEqual(output["policy_tokens"], 25)
        self.assertEqual(next(item for item in output["trace"] if item["node"] == "planner")["attempts"], 2)
        self.assertIn("invalid task tool", model.calls[2]["validation_error"])
        self.assertNotIn("git", [name for name, _ in tools.calls])

    def test_workflow_validator_rejects_repeated_lookups_and_skipped_reproduction(self):
        artifact = json.loads((self.root / "team" / "team-artifact.json").read_text())
        features = json.loads((self.root / "feature-map.json").read_text())
        plan = {"domain_ids": ["checkout"], "feature_names": [], "tasks": [
            {"id": "first", "tool": "admin_lookup", "arguments": {"account_id": "acct-123"}, "depends_on": []},
            {"id": "second", "tool": "admin_lookup", "arguments": {"account_id": "acct-123"}, "depends_on": []},
        ]}
        with self.assertRaisesRegex(ValueError, "one admin_lookup"):
            _validate_plan(plan, artifact, features, False, "acct-123", "Reproduce acct-123 issue", "bug_analysis")
        plan["tasks"].pop()
        with self.assertRaisesRegex(ValueError, "add a reproduce_backend"):
            _validate_plan(plan, artifact, features, False, "acct-123", "Reproduce acct-123 issue", "bug_analysis")

    def test_response_rejects_unsupported_results_and_unknown_evidence(self):
        answer = {"summary": "Investigated", "findings": [], "evidence": [], "remaining_work": []}
        tasks = [{"id": "lookup"}]
        self.assertEqual(validate_response(answer, tasks), answer)
        with self.assertRaisesRegex(ValueError, "unsupported fields"):
            validate_response({**answer, "results": [{"status": "invented"}]}, tasks)
        with self.assertRaisesRegex(ValueError, "unknown task ID"):
            validate_response({**answer, "evidence": [{"task_id": "imaginary"}]}, tasks)
        with self.assertRaisesRegex(ValueError, "candidate"):
            validate_response(answer, tasks, "release_impact")
        with self.assertRaisesRegex(ValueError, "affected_features"):
            validate_response({**answer, "summary": "Potential checkout impact"}, tasks, "release_impact")
        release_answer = {**answer, "summary": "Potential checkout impact", "affected_features": [],
                          "owners": [], "consumers": [], "tests": []}
        self.assertEqual(validate_response(release_answer, tasks, "release_impact")["summary"],
                         "Potential checkout impact")

    def test_failed_dependency_blocks_followup(self):
        class FailingTools(FakeTools):
            def execute(self, name, arguments):
                self.calls.append((name, arguments))
                return {"status": "unavailable"} if name == "jira_search" else {"status": "ok"}

        tools = FailingTools()
        graph = create_graph(self.root, model=FakeModel(self.plan()), tools=tools)
        output = graph.invoke({"request": {"text": "Checkout fails"}},
                              config={"configurable": {"thread_id": "request-2"}})
        self.assertEqual(output["answer"]["task_status"]["analysis"], "blocked")
        self.assertNotIn("codebot", [name for name, _ in tools.calls])

    def test_independent_workers_run_concurrently(self):
        barrier = threading.Barrier(2)

        class ConcurrentTools(FakeTools):
            def execute(self, name, arguments):
                if name in {"github_recent_commits", "jira_search"}:
                    barrier.wait(timeout=2)
                return super().execute(name, arguments)

        graph = create_graph(self.root, model=FakeModel(self.plan()), tools=ConcurrentTools())
        output = graph.invoke({"request": {"text": "Checkout fails"}},
                              config={"configurable": {"thread_id": "parallel"}})
        self.assertEqual(output["answer"]["task_status"]["analysis"], "completed")

    def test_unknown_repository_and_cycles_are_rejected(self):
        artifact = json.loads((self.root / "team" / "team-artifact.json").read_text())
        features = json.loads((self.root / "feature-map.json").read_text())
        plan = self.plan()
        plan["tasks"][0]["arguments"]["repository"] = "other/repo"
        with self.assertRaisesRegex(ValueError, "outside the selected domain"):
            _validate_plan(plan, artifact, features, False)
        plan = self.plan()
        plan["tasks"][0]["depends_on"] = ["analysis"]
        with self.assertRaisesRegex(ValueError, "cycle"):
            _validate_plan(plan, artifact, features, False)
        with self.assertRaisesRegex(ValueError, "account-scoped"):
            _validate_plan(self.plan(), artifact, features, False, "acct-123")
        ticket = {"domain_ids": ["checkout"], "feature_names": [], "tasks": [
            {"id": "ticket", "tool": "jira_create", "arguments": {"summary": "New feature"},
             "depends_on": []}]}
        with self.assertRaisesRegex(ValueError, "disabled by policy"):
            _validate_plan(ticket, artifact, features, False)
        self.assertEqual(_validate_plan(ticket, artifact, features, True)["tasks"][0]["tool"],
                         "jira_create")

    def test_malformed_model_lists_are_repairable_validation_errors(self):
        artifact = json.loads((self.root / "team" / "team-artifact.json").read_text())
        features = json.loads((self.root / "feature-map.json").read_text())
        with self.assertRaisesRegex(ValueError, "unknown domains"):
            _validate_plan({"domain_ids": [["checkout"]], "feature_names": [], "tasks": []},
                           artifact, features, False)
        plan = self.plan()
        plan["tasks"][0]["depends_on"] = [["tickets"]]
        with self.assertRaisesRegex(ValueError, "depends_on"):
            _validate_plan(plan, artifact, features, False)
        answer = {"summary": "Investigated", "findings": [{"claim": "Issue",
                  "evidence_tasks": [["history"]]}], "evidence": [], "remaining_work": []}
        with self.assertRaisesRegex(ValueError, "unknown task ID"):
            validate_response(answer, [{"id": "history"}])

    def test_explicit_account_in_text_routes_to_lookup(self):
        plan = {"domain_ids": ["checkout"], "feature_names": [], "tasks": [
            {"id": "customer", "tool": "admin_lookup", "arguments": {"account_id": "acct-123"},
             "depends_on": []}]}

        class AccountModel(FakeModel):
            def complete_json(self, system, payload):
                if "team_artifact" not in payload and "results" not in payload:
                    return {"capability": "bug_analysis", "account_id": "acct-123"}, 3
                return super().complete_json(system, payload)

        tools = FakeTools()
        graph = create_graph(self.root, model=AccountModel(plan), tools=tools)
        state = graph.invoke({"request": {"text": "Investigate account acct-123 checkout errors"}},
                             config={"configurable": {"thread_id": "account"}})
        self.assertEqual(state["request"]["account_id"], "acct-123")
        self.assertEqual(tools.calls[0][1]["account_id"], "acct-123")

    def test_release_impact_maps_changed_paths_to_features(self):
        tasks = [{"id": "compare", "tool": "github_compare", "arguments": {"repository": "org/api"}}]
        results = [{"task_id": "compare", "outcome": {"status": "ok", "data": {"files": [
            {"filename": "checkout/submit.py"}, {"filename": "billing/invoice.py"}]}}}]
        features = {"features": [{"name": "submission", "repositories": ["org/api"],
                                  "path_globs": {"org/api": ["checkout/*"]},
                                  "consumers": ["org/web"]}]}
        matched = impact_candidates(tasks, results, features)
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["file"], "checkout/submit.py")
        self.assertEqual(matched[0]["consumers"], ["org/web"])

    def test_multi_repo_harness_routes_frontend_and_backend_workers(self):
        artifact = {"domains": [{"id": "checkout", "repositories": [
            {"name": "org/web", "kind": "frontend", "responsibility": "checkout form",
             "signals": ["submit button"], "depends_on": ["org/api"]},
            {"name": "org/api", "kind": "backend", "responsibility": "order creation",
             "signals": ["order POST"], "depends_on": []},
            {"name": "org/admin", "kind": "frontend", "responsibility": "operations dashboard"},
        ]}]}
        features = {"features": [{"name": "submission", "repositories": ["org/web", "org/api"],
                    "components": [
                        {"repository": "org/web", "role": "form", "path_globs": ["src/checkout/**"]},
                        {"repository": "org/api", "role": "endpoint", "path_globs": ["src/orders/**"]},
                    ]}]}
        (self.root / "team" / "team-artifact.json").write_text(json.dumps(artifact))
        (self.root / "feature-map.json").write_text(json.dumps(features))
        plan = {"domain_ids": ["checkout"], "feature_names": ["submission"], "tasks": [
            {"id": "ui", "tool": "codebot", "arguments": {"repository": "org/web", "task": "update form"}, "depends_on": []},
            {"id": "api", "tool": "codebot", "arguments": {"repository": "org/api", "task": "update endpoint"}, "depends_on": []},
        ]}
        graph = create_graph(self.root, model=FakeModel(plan), tools=FakeTools())
        output = graph.invoke({"request": {"text": "Add a checkout submission feature"}, "capability": "feature"},
                              config={"configurable": {"thread_id": "multi-repo"}})
        self.assertEqual(output["context"]["repository_catalog"]["org/web"]["kind"], "frontend")
        self.assertEqual(output["plan"]["focus_repositories"], ["org/api", "org/web"])
        self.assertEqual(evaluate_trajectory(output, {
            "capability": "feature", "required_focus_repositories": ["org/api", "org/web"],
            "forbidden_focus_repositories": ["org/admin"],
            "parallel_tools": [["codebot", "codebot"]],
        })["reward"], 1.0)

    def test_harness_rejects_unknown_dependency_and_component(self):
        artifact = {"domains": [{"id": "d", "repositories": [
            {"name": "org/web", "kind": "frontend", "depends_on": ["org/missing"]}]}]}
        with self.assertRaisesRegex(ValueError, "repository dependency"):
            build_repository_catalog(artifact, {"features": []})
        artifact["domains"][0]["repositories"][0]["depends_on"] = []
        with self.assertRaisesRegex(ValueError, "component outside"):
            build_repository_catalog(artifact, {"features": [{"name": "f", "repositories": ["org/web"],
                "components": [{"repository": "org/missing", "role": "endpoint"}]}]})

    def test_release_impact_reports_exact_feature_component(self):
        tasks = [{"id": "compare", "tool": "github_compare", "arguments": {"repository": "org/web"}}]
        results = [{"task_id": "compare", "outcome": {"data": {"files": [
            {"filename": "src/checkout/form.tsx"}, {"filename": "src/admin/report.tsx"}]}}}]
        features = {"features": [{"name": "submission", "repositories": ["org/web"],
            "components": [{"repository": "org/web", "role": "checkout form",
                            "path_globs": ["src/checkout/**"], "tests": ["tests/form.spec.ts"]}]}]}
        candidates = impact_candidates(tasks, results, features)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["component_role"], "checkout form")
        self.assertEqual(candidates[0]["tests"], ["tests/form.spec.ts"])

    def test_trajectory_eval_checks_tools_parallel_wave_and_dependency(self):
        graph = create_graph(self.root, model=FakeModel(self.plan()), tools=FakeTools())
        output = graph.invoke({"request": {"text": "Checkout fails"}},
                              config={"configurable": {"thread_id": "trajectory"}})
        expected = {"capability": "bug_analysis", "required_domains": ["checkout"],
                    "required_tools": ["github_recent_commits", "jira_search", "codebot"],
                    "tool_repositories": {"codebot": ["org/web"]},
                    "parallel_tools": [["github_recent_commits", "jira_search"]],
                    "dependencies": [{"before": "jira_search", "after": "codebot"}]}
        self.assertEqual(evaluate_trajectory(output, expected)["reward"], 1.0)
        wrong = {**expected, "required_tools": ["splunk_search"],
                 "parallel_tools": [["codebot", "jira_search"]]}
        verdict = evaluate_trajectory(output, wrong)
        self.assertIn("required_tool:splunk_search", verdict["failure_tags"])
        self.assertIn("parallel_group:0", verdict["failure_tags"])

    def test_trajectory_suite_covers_all_six_capabilities_and_account_branch(self):
        cases = json.loads((Path(__file__).resolve().parents[1] / "examples" /
                            "trajectory_cases.json").read_text())
        self.assertEqual({case["expected_trajectory"]["capability"] for case in cases},
                         {"bug_analysis", "bug_fix", "feature", "pr_review", "release_impact", "tech_debt"})
        self.assertTrue(any(case["expected_trajectory"].get("account_id") for case in cases))

    def test_github_pr_files_are_paginated(self):
        pages = []

        def handle(request):
            page = int(request.url.params["page"])
            pages.append(page)
            count = 100 if page == 1 else 1
            return httpx.Response(200, json=[{"filename": f"src/file-{page}-{index}.py",
                                             "status": "modified", "patch": "+line"}
                                            for index in range(count)])

        client = httpx.Client(transport=httpx.MockTransport(handle))
        result = HTTPTools(client=client, env={"GITHUB_API_URL": "https://github.test"}).execute(
            "github_pr_files", {"repository": "org/api", "pr_number": 42})
        self.assertEqual(pages, [1, 2])
        self.assertEqual(len(result["data"]), 101)
        self.assertFalse(result["truncated"])

    def test_codebot_stub_does_not_echo_request_context(self):
        result = HTTPTools(env={}).execute("codebot", {"request": {"text": "sensitive context"}})
        self.assertEqual(result["status"], "stub")
        self.assertNotIn("sensitive context", json.dumps(result))

    def test_trajectory_verifier_uses_rrsi_json_protocol(self):
        graph = create_graph(self.root, model=FakeModel(self.plan()), tools=FakeTools())
        state = graph.invoke({"request": {"text": "Checkout fails"}},
                             config={"configurable": {"thread_id": "verifier-protocol"}})
        payload = {"task": {"expected_trajectory": {"capability": "bug_analysis",
                                                    "required_tools": ["jira_search", "codebot"]}},
                   "agent_output": state, "workspace": self.tmp.name}
        process = subprocess.run(
            [sys.executable, "-m", "on_call_assistant.evaluation.cli", "verify-rrsi"],
            input=json.dumps(payload), text=True, capture_output=True, check=True,
        )
        self.assertEqual(json.loads(process.stdout)["reward"], 1.0)

    def test_service_exposes_checkpointed_status(self):
        graph = create_graph(self.root, model=FakeModel(self.plan()), tools=FakeTools())
        client = TestClient(create_app(graph=graph, api_token="test-token"))
        headers = {"Authorization": "Bearer test-token"}
        self.assertEqual(client.post("/requests", json={"text": "Checkout fails"}).status_code, 401)
        created = client.post("/requests", json={"text": "Checkout fails"}, headers=headers).json()
        self.assertEqual(created["status"], "queued")
        for _ in range(50):
            fetched = client.get(f"/requests/{created['request_id']}", headers=headers).json()
            if fetched["status"] == "completed":
                break
            time.sleep(0.01)
        self.assertEqual(fetched["status"], "completed")
        self.assertEqual(fetched["tasks"], graph.get_state(
            {"configurable": {"thread_id": created["request_id"]}}).values["tasks"])
        self.assertEqual(client.get("/requests/missing", headers=headers).status_code, 404)

    def test_service_shows_running_tasks_before_completion(self):
        release = threading.Event()
        started = threading.Event()
        plan = {"domain_ids": ["checkout"], "feature_names": [], "tasks": [
            {"id": "history", "tool": "jira_search", "arguments": {"query": "checkout"},
             "depends_on": []}]}

        class WaitingTools(FakeTools):
            def execute(self, name, arguments):
                started.set()
                if not release.wait(timeout=3):
                    return {"status": "error", "error": "timed out waiting for test"}
                return super().execute(name, arguments)

        graph = create_graph(self.root, model=FakeModel(plan), tools=WaitingTools())
        headers = {"Authorization": "Bearer test-token"}
        try:
            with TestClient(create_app(graph=graph, api_token="test-token")) as client:
                created = client.post("/requests", json={"text": "Checkout fails"}, headers=headers).json()
                self.assertTrue(started.wait(timeout=2))
                progress = client.get(f"/requests/{created['request_id']}", headers=headers).json()
                self.assertEqual(progress["status"], "running")
                self.assertEqual(progress["tasks"][0]["status"], "running")
                release.set()
                for _ in range(50):
                    progress = client.get(f"/requests/{created['request_id']}", headers=headers).json()
                    if progress["status"] == "completed":
                        break
                    time.sleep(0.01)
                self.assertEqual(progress["tasks"][0]["status"], "completed")
        finally:
            release.set()


if __name__ == "__main__":
    unittest.main()
