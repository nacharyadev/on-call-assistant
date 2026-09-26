import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from on_call_assistant.evaluation.dry_run import DryRunTools
from on_call_assistant.evaluation.live_runner import run_trial
from on_call_assistant.evolution.core import Config, load_tasks
from on_call_assistant.evolution.model_adapters import critique, propose


class StubModel:
    def __init__(self, response):
        self.response = response
        self.payload = None

    def complete_json(self, system, payload):
        self.payload = payload
        return self.response, 12


class LiveDemoTests(unittest.TestCase):
    def test_proposer_edits_only_planner_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            prompt = Path(directory) / "prompts" / "planner.txt"
            prompt.parent.mkdir()
            prompt.write_text("Original planner\n", encoding="utf-8")
            model = StubModel({"replacement_prompt": "Improved planner", "hypothesis": "Clearer routing"})
            result = propose({"incumbent_harness_dir": directory, "feedback": {"failure_tags": {}},
                              "history": [], "edit_budget": 1}, model)
            self.assertEqual(result["candidates"][0]["edits"][0]["path"], "prompts/planner.txt")
            self.assertEqual(result["candidates"][0]["edits"][0]["content"], "Improved planner\n")
            self.assertNotIn("expected_trajectory", model.payload)

    def test_critic_rejects_non_prompt_edits_before_model_call(self):
        model = StubModel({"approved": True, "reason": "generic"})
        result = critique({"edits": [{"path": "team/team-artifact.json", "component": "memory"}]}, model)
        self.assertFalse(result["approved"])
        self.assertIsNone(model.payload)

    def test_runner_uses_dry_run_tools_and_exposes_full_trace(self):
        class Graph:
            def invoke(self, state, config):
                self.request = state["request"]
                self.thread_id = config["configurable"]["thread_id"]
                return {"answer": {"summary": "done"}, "capability": "bug_analysis",
                        "policy_tokens": 18, "trace": [{"node": "worker", "tool": "jira_search"}],
                        "tasks": [{"id": "t1", "tool": "jira_search"}], "plan": {}}

        graph = Graph()
        with patch("on_call_assistant.evaluation.live_runner.create_graph", return_value=graph) as factory:
            result = run_trial({"task": {"id": "case", "input": {"text": "Investigate"}},
                                "harness_dir": "/tmp/harness", "seed": 7})
        self.assertIsInstance(factory.call_args.kwargs["tools"], DryRunTools)
        self.assertEqual(graph.thread_id, "rrsi-case-7")
        self.assertEqual(result["policy_tokens"], 18)
        self.assertEqual(result["trace"][0]["tool"], "jira_search")

    def test_live_config_has_disjoint_tasks(self):
        examples = Path(__file__).resolve().parents[1] / "examples"
        config = Config.load(examples / "live.json")
        evolve = load_tasks(config.evolve_tasks)
        heldout = load_tasks(config.heldout_tasks)
        self.assertFalse({task["id"] for task in evolve} & {task["id"] for task in heldout})
        self.assertIn("prds", config.protected_paths)
