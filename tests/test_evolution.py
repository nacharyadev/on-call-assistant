import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from on_call_assistant.evolution.core import (Config, apply_candidate, edit_budget, exploration_state,
                              screen_leakage, select_candidate)


ROOT = Path(__file__).resolve().parents[1]


class HarnessEvolutionTests(unittest.TestCase):
    def setUp(self):
        self.config = Config.load(ROOT / "examples" / "demo.json")

    def test_annealed_budget_falls_to_one(self):
        budgets = [edit_budget(t, 8, 1, 4) for t in range(9)]
        self.assertEqual(budgets[0], 4)
        self.assertEqual(budgets[-1], 1)
        self.assertEqual(budgets, sorted(budgets, reverse=True))

    def test_candidate_edits_cannot_escape_harness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "prompt.txt").write_text("old")
            with self.assertRaises(ValueError):
                apply_candidate(source, root / "candidate", [{
                    "component": "prompt", "hypothesis": "escape", "path": "../outside.txt",
                    "operation": "add", "content": "bad",
                }], 1)
            self.assertFalse((root / "outside.txt").exists())

    def test_ground_truth_is_protected_and_index_edits_need_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            (source / "prds").mkdir(parents=True)
            (source / "prds" / "requirements.md").write_text("ground truth")
            (source / "feature-map.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "protected source artifact"):
                apply_candidate(source, root / "protected", [{
                    "component": "memory", "hypothesis": "rewrite source", "path": "prds/requirements.md",
                    "operation": "replace", "content": "new claim",
                }], 1, protected_paths=("prds",))
            with self.assertRaisesRegex(ValueError, "needs source references"):
                apply_candidate(source, root / "uncited", [{
                    "component": "memory", "hypothesis": "new mapping", "path": "feature-map.json",
                    "operation": "replace", "content": '{"feature":"checkout"}',
                }], 1, evidence_required_paths=("feature-map.json",))
            diff = apply_candidate(source, root / "cited", [{
                "component": "memory", "hypothesis": "new mapping", "path": "feature-map.json",
                "operation": "replace", "content": '{"feature":"checkout"}',
                "sources": ["prds/requirements.md"],
            }], 1, evidence_required_paths=("feature-map.json",))
            self.assertIn("checkout", diff)

    def test_leakage_screen_runs_on_diff(self):
        tasks = [{"id": "incident-12345", "forbidden_terms": ["private-answer"]}]
        self.assertIn("incident-12345", screen_leakage("+incident-12345", tasks))
        self.assertIsNone(screen_leakage("+Inspect failing calls generically", tasks))

    def test_stability_floor_blocks_sequential_regression(self):
        incumbent = {"score": 0.81, "policy_tokens": 100,
                     "capability_scores": {"bug_fix": 0.81}}
        candidate = {"edits": [{"component": "skill"}],
                     "evaluation": {"score": 0.79, "policy_tokens": 50,
                                    "capability_scores": {"bug_fix": 0.79}}}
        accepted, reason, _, _ = select_candidate(candidate, incumbent, 0.85, 0.03, [], self.config)
        self.assertFalse(accepted)
        self.assertEqual(reason, "below stability floor")

    def test_cost_rule_rejects_expensive_small_gain(self):
        config = replace(self.config, beta0=0.1, beta1=1.0, max_capability_drop=1)
        incumbent = {"score": 0.5, "policy_tokens": 100,
                     "capability_scores": {"bug_fix": 0.5}}
        candidate = {"edits": [{"component": "prompt"}],
                     "evaluation": {"score": 0.6, "policy_tokens": 150,
                                    "capability_scores": {"bug_fix": 0.6}}}
        accepted, reason, _, _ = select_candidate(candidate, incumbent, 0.5, 0.01, [], config)
        self.assertFalse(accepted)
        self.assertEqual(reason, "cost exceeds gain allowance")

    def test_capability_regression_is_noncompensatory(self):
        incumbent = {"score": 0.5, "policy_tokens": 100,
                     "capability_scores": {"bug_fix": 0.5, "feature": 0.5}}
        candidate = {"edits": [{"component": "prompt"}],
                     "evaluation": {"score": 0.6, "policy_tokens": 100,
                                    "capability_scores": {"bug_fix": 0.3, "feature": 0.9}}}
        accepted, reason, _, _ = select_candidate(candidate, incumbent, 0.5, 0.01, [], self.config)
        self.assertFalse(accepted)
        self.assertEqual(reason, "regression in bug_fix")

    def test_domain_regression_is_noncompensatory(self):
        incumbent = {"score": 0.5, "policy_tokens": 100,
                     "capability_scores": {"bug_fix": 0.5},
                     "domain_scores": {"checkout": 0.8, "platform": 0.2}}
        candidate = {"edits": [{"component": "memory"}],
                     "evaluation": {"score": 0.6, "policy_tokens": 100,
                                    "capability_scores": {"bug_fix": 0.6},
                                    "domain_scores": {"checkout": 0.6, "platform": 0.6}}}
        accepted, reason, _, _ = select_candidate(candidate, incumbent, 0.5, 0.01, [], self.config)
        self.assertFalse(accepted)
        self.assertEqual(reason, "regression in domain checkout")

    def test_history_directs_exploration_and_pruning(self):
        history = [{"round": 0, "component": "prompt", "delta_score": -0.1,
                    "accepted": False}]
        state = exploration_state(history, [0.4, 0.4, 0.4, 0.4], 3, 0.01, self.config)
        self.assertTrue(state["stalled"])
        self.assertIn("prompt", state["prune_components"])
        self.assertIn("skill", state["untried_components"])


if __name__ == "__main__":
    unittest.main()
