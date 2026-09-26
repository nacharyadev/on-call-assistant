"""Deterministic demonstration of the command protocol; not an agent benchmark."""

import json
import sys
from pathlib import Path


def main() -> None:
    payload = json.load(sys.stdin)
    mode = sys.argv[1]
    if mode == "propose":
        harness = json.loads((Path(payload["incumbent_harness_dir"]) / "harness.json").read_text())
        enabled = set(harness["enabled_recipes"])
        scores = payload["feedback"]["capability_scores"]
        choices = [name for name, score in sorted(scores.items(), key=lambda x: (x[1], x[0])) if name not in enabled]
        components = ["prompt", "control_flow", "client_tool", "context_mgmt", "skill", "memory"]
        candidates = []
        for choice in choices[:payload["max_candidates"]]:
            updated = {**harness, "enabled_recipes": sorted(enabled | {choice})}
            candidates.append({"edits": [{
                "component": components[len(enabled) % len(components)],
                "hypothesis": f"A reusable {choice} recipe improves this workflow",
                "path": "harness.json", "operation": "replace",
                "content": json.dumps(updated, indent=2, sort_keys=True) + "\n",
            }]})
        print(json.dumps({"candidates": candidates}))
    elif mode == "run":
        harness = json.loads((Path(payload["harness_dir"]) / "harness.json").read_text())
        task = payload["task"]
        enabled = task["capability"] in harness["enabled_recipes"]
        print(json.dumps({"answer": task["input"]["choices"][1 if enabled else 0],
                          "policy_tokens": 100 + 5 * len(harness["enabled_recipes"])}))
    elif mode == "verify":
        task, output = payload["task"], payload["agent_output"]
        correct = output.get("answer") == task["expected"]
        print(json.dumps({"reward": int(correct),
                          "failure_tags": [] if correct else ["missing_workflow_recipe"]}))
    elif mode == "critic":
        # A real experiment should replace this with a semantic leakage critic.
        print(json.dumps({"approved": True, "reason": "demo candidate is generic"}))
    else:
        raise SystemExit(f"unknown mode: {mode}")


if __name__ == "__main__":
    main()
