import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from on_call_assistant.api.service import create_app
from on_call_assistant.evaluation.captured_flows import RecordedFlowTools, export_drafts
from on_call_assistant.evaluation.live_runner import run_trial


class CaptureGraph:
    def invoke(self, state, config):
        return {
            "capability": "bug_analysis",
            "classification": {"capability": "bug_analysis"},
            "plan": {"domain_ids": ["inventory"], "repositories": ["acme/inventory-api"]},
            "tasks": [{"id": "history", "tool": "jira_search", "status": "completed",
                       "arguments": {"query": "material shortage"}, "depends_on": []}],
            "results": [{"task_id": "history", "tool": "jira_search",
                         "outcome": {"status": "ok", "data": {"issue": "INV-1", "token": "private"}}}],
            "trace": [{"node": "dispatch", "ready": ["history"]},
                      {"node": "worker", "task_id": "history", "tool": "jira_search"}],
            "answer": {"summary": "Checked account", "routing": {"domains": ["inventory"],
                       "repositories": ["acme/inventory-api"]}},
            "policy_tokens": 42,
        }


class FlowCaptureTests(unittest.TestCase):
    def test_service_captures_and_exports_replayable_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness = root / "harness"
            harness.mkdir()
            (harness / "feature-map.json").write_text("{}", encoding="utf-8")
            captures = root / "captures"
            headers = {"Authorization": "Bearer test-token"}
            with TestClient(create_app(harness, graph=CaptureGraph(), api_token="test-token",
                                       capture_dir=captures)) as client:
                response = client.post("/requests", headers=headers, json={
                    "text": "Investigate acct-7; Bearer abc123; email me@example.com",
                    "account_id": "acct-7", "capability": "bug_analysis",
                    "metadata": {"api_key": "secret-value"},
                })
                self.assertEqual(response.status_code, 202)
                request_id = response.json()["request_id"]
                path = captures / f"{request_id}.json"
                for _ in range(100):
                    if path.exists() and json.loads(path.read_text())["status"] == "completed":
                        break
                    time.sleep(0.01)
            record = json.loads(path.read_text())
            self.assertEqual(record["status"], "completed")
            self.assertEqual(record["policy_tokens"], 42)
            self.assertEqual(record["observed_trajectory"]["waves"][0][0]["tool"], "jira_search")
            self.assertEqual(record["results"][0]["outcome"]["data"]["token"], "[REDACTED]")
            self.assertNotIn("secret-value", path.read_text())
            self.assertNotIn("abc123", path.read_text())
            self.assertNotIn("me@example.com", path.read_text())
            self.assertEqual(os.stat(captures).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertIsNotNone(record["harness_sha256"])
            snapshot = captures / record["harness_snapshot"]
            self.assertEqual((snapshot / "feature-map.json").read_text(), "{}")
            self.assertEqual(os.stat(snapshot / "feature-map.json").st_mode & 0o777, 0o600)

            output = root / "drafts.json"
            self.assertEqual(export_drafts(captures, output), 1)
            draft = json.loads(output.read_text())[0]
            self.assertEqual(draft["capability"], "bug_analysis")
            self.assertEqual(draft["domain"], "inventory")
            self.assertNotIn("expected_trajectory", draft)
            replay = RecordedFlowTools(draft["recorded_tools"])
            self.assertEqual(replay.execute("jira_search", {"query": "material shortage"})["status"], "ok")
            self.assertEqual(replay.execute("jira_search", {"query": "different"})["status"], "unavailable")

    def test_runner_uses_recorded_tools_when_supplied(self):
        class Graph:
            def invoke(self, state, config):
                self.tools_result = tools.execute("jira_search", {"query": "q"})
                return {"answer": {}, "capability": "bug_analysis", "trace": [],
                        "tasks": [], "plan": {}, "policy_tokens": 0}

        graph = Graph()
        def factory(*args, **kwargs):
            nonlocal tools
            tools = kwargs["tools"]
            return graph
        tools = None
        with patch("on_call_assistant.evaluation.live_runner.create_graph", side_effect=factory):
            run_trial({"task": {"id": "case", "input": {"text": "x"},
                                "recorded_tools": [{"tool": "jira_search", "arguments": {"query": "q"},
                                                    "outcome": {"status": "ok", "data": {"id": 1}}}]},
                       "harness_dir": "/tmp/harness", "seed": 1})
        self.assertIsInstance(tools, RecordedFlowTools)
        self.assertEqual(graph.tools_result["data"]["id"], 1)

    def test_failed_flow_keeps_input_and_error(self):
        class FailingGraph:
            def invoke(self, state, config):
                raise RuntimeError("backend failed")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness = root / "harness"
            harness.mkdir()
            captures = root / "captures"
            with TestClient(create_app(harness, graph=FailingGraph(), api_token="test-token",
                                       capture_dir=captures)) as client:
                response = client.post("/requests", headers={"Authorization": "Bearer test-token"},
                                       json={"text": "Investigate failure"})
                self.assertEqual(response.status_code, 202)
                path = captures / f"{response.json()['request_id']}.json"
                for _ in range(100):
                    if path.exists() and json.loads(path.read_text())["status"] == "failed":
                        break
                    time.sleep(0.01)
            record = json.loads(path.read_text())
            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["error"], "backend failed")
            self.assertEqual(record["input"]["text"], "Investigate failure")


if __name__ == "__main__":
    unittest.main()
