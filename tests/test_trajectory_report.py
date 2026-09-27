import json
import tempfile
import unittest
from pathlib import Path

from on_call_assistant.evaluation.report import capture_actual, render_html, write_reports


class TrajectoryReportTests(unittest.TestCase):
    def test_expected_and_actual_route_render_without_executing_embedded_markup(self):
        state = {
            "capability": "bug_analysis",
            "tasks": [
                {"id": "lookup", "tool": "admin_lookup", "arguments": {"account_id": "acct-123"},
                 "depends_on": [], "status": "completed"},
                {"id": "repro", "tool": "reproduce_backend",
                 "arguments": {"repository": "example/checkout-api"},
                 "depends_on": ["lookup"], "status": "completed"},
            ],
            "trace": [{"node": "dispatch", "ready": ["lookup"]},
                      {"node": "worker", "task_id": "lookup", "tool": "admin_lookup"},
                      {"node": "dispatch", "ready": ["repro"]},
                      {"node": "worker", "task_id": "repro", "tool": "reproduce_backend"}],
            "results": [{"task_id": "lookup", "outcome": {"secret": "do-not-copy"}}],
            "answer": {"routing": {"domains": ["checkout"], "features": [],
                                   "repositories": ["example/checkout-api"],
                                   "focus_repositories": ["example/checkout-api"]},
                       "summary": "Reproduced <script>alert(1)</script>"},
        }
        actual = capture_actual(state)
        self.assertNotIn("do-not-copy", json.dumps(actual))
        record = {"id": "account-incident", "request": "Investigate <b>checkout</b>",
                  "expected_trajectory": {"capability": "bug_analysis", "account_id": "acct-123",
                                          "required_tools": ["admin_lookup", "reproduce_backend"],
                                          "dependencies": [{"before": "admin_lookup", "after": "reproduce_backend"}]},
                  "actual": actual,
                  "verdict": {"reward": 1.0, "failure_tags": [],
                              "checks": [{"name": "node_sequence", "passed": True}]}}
        page = render_html([record])
        self.assertIn("Expected · case JSON", page)
        self.assertIn("Actual · graph run", page)
        self.assertIn("admin_lookup → reproduce_backend", page)
        self.assertIn("acct-123", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("Investigate &lt;b&gt;checkout&lt;/b&gt;", page)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_reports([record], json_path=root / "report.json", html_path=root / "report.html")
            saved = json.loads((root / "report.json").read_text())
            self.assertEqual(saved[0]["actual"]["waves"][0][0]["tool"], "admin_lookup")
            self.assertIn("Trajectory ledger", (root / "report.html").read_text())


if __name__ == "__main__":
    unittest.main()
