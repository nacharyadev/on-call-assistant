import json
import unittest

from examples.supply_chain.fixtures import RecordedTools, ROOT
from examples.supply_chain.mini_services import replay_material_issue
from examples.supply_chain.run import run_case
from examples.supply_chain.verifier import _states_tentative_impact
from on_call_assistant.knowledge.catalog import build_repository_catalog


CASES = {case["id"]: case for case in json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))}


class SupplyChainExampleTests(unittest.TestCase):
    def test_harness_has_multiple_frontend_and_backend_repos_per_domain(self):
        harness = ROOT / "harness"
        artifact = json.loads((harness / "team" / "team-artifact.json").read_text())
        features = json.loads((harness / "feature-map.json").read_text())
        catalog = build_repository_catalog(artifact, features)
        for domain in artifact["domains"]:
            kinds = [catalog[entry["name"]]["kind"] for entry in domain["repositories"]]
            self.assertGreaterEqual(kinds.count("frontend"), 2)
            self.assertGreaterEqual(kinds.count("backend"), 2)
        operator_flow = next(item for item in features["features"]
                             if item["name"] == "operator material issue workflow")
        self.assertEqual({catalog[component["repository"]]["kind"]
                          for component in operator_flow["components"]}, {"frontend", "backend"})
        self.assertEqual(len(operator_flow["components"]), 6)

    def test_release_impact_requires_tentative_language(self):
        self.assertTrue(_states_tentative_impact("This is a plausible risk, not a confirmed regression."))
        self.assertFalse(_states_tentative_impact("This is a proven regression."))

    def test_backend_replay_shows_ledger_and_mes_failure(self):
        replay = replay_material_issue()
        self.assertTrue(replay["bug_reproduced"])
        self.assertEqual(replay["observed"]["first"]["inventory_available"], 80)
        self.assertEqual(replay["observed"]["retry"]["inventory_available"], 0)
        self.assertEqual(replay["observed"]["retry"]["warehouse_physical"], 80)
        self.assertEqual(replay["observed"]["work_order_http_status"], 409)
        self.assertEqual(replay["reference_event_id_dedupe"]["work_order_http_status"], 200)

    def test_incident_and_release_pass_path_and_outcome_checks(self):
        for case in CASES.values():
            with self.subTest(case=case["id"]):
                result = run_case(case)
                self.assertTrue(result["passed"], result)
                self.assertEqual(result["trajectory"]["reward"], 1.0)
                self.assertTrue(result["outcome"]["passed"])
                self.assertEqual(result["answer"]["task_status"]["code_analysis"], "stub")

    def test_missing_duplicate_log_keeps_path_but_fails_outcome(self):
        class MissingDelivery(RecordedTools):
            def execute(self, name, arguments):
                result = super().execute(name, arguments)
                if name == "splunk_search":
                    result = json.loads(json.dumps(result))
                    result["data"]["deliveries"] = result["data"]["deliveries"][:1]
                return result

        result = run_case(CASES["account-material-issue"], tools=MissingDelivery())
        self.assertEqual(result["trajectory"]["reward"], 1.0)
        self.assertFalse(result["outcome"]["passed"])
        self.assertIn("same_event_two_deliveries", result["outcome"]["failure_tags"])

    def test_missing_repository_change_fails_release_outcome(self):
        class MissingDiff(RecordedTools):
            def execute(self, name, arguments):
                result = super().execute(name, arguments)
                if name == "github_compare" and arguments["repository"] == "northstar/inventory-ledger":
                    result = json.loads(json.dumps(result))
                    result["data"]["files"] = []
                return result

        result = run_case(CASES["release-material-issue"], tools=MissingDiff())
        self.assertEqual(result["trajectory"]["reward"], 1.0)
        self.assertFalse(result["outcome"]["passed"])
        self.assertIn("path_matched_impact", result["outcome"]["failure_tags"])


if __name__ == "__main__":
    unittest.main()
