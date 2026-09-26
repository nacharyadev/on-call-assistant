---
name: oca-harness-trajectory-evals
description: Create or update OCA trajectory cases that verify capability routing, repo focus, tool selection, dependencies, and parallel worker waves.
---

# Prepare OCA trajectory cases

Create or update a JSON array of cases, commonly `trajectory_cases.json`. Read the team artifact and feature map first, then use `examples/trajectory_cases.json` for the current case format and `docs/agent.md` for evaluator behavior.

## Build independent expected paths

- Give each case a stable unique `id`, a realistic public request in `input.text`, and `expected_trajectory` grounded in the team's intended operating procedure.
- For a full team suite, cover all six supported capabilities: `bug_analysis`, `bug_fix`, `feature`, `pr_review`, `release_impact`, and `tech_debt`. When asked for a single case or capability, add only that path and report any coverage gaps separately. Include account-scoped and cross-repository paths when the team uses them.
- Assert the capability, required domains, required repositories, and tools. Use `required_focus_repositories` to check repos with actual repository-scoped tasks; use `forbidden_focus_repositories` to catch irrelevant UI/backend fanout.
- Use `tool_repositories` when tool-to-repo assignment matters, `dependencies` for required task ordering, and `parallel_tools` for independent workers expected in the same dispatch wave. Do not require ordering among parallel results.
- Add `forbidden_tools` when a sensitive or irrelevant action must not be planned. Keep Jira creation disabled in ordinary cases; a write-path eval should be isolated and explicitly authorized for a test project.
- Keep the expected path separate from tool output and answer correctness. The suite invokes `DryRunTools`; it checks routing decisions, not live integrations, diagnosis correctness, or patch quality. Add a separate verifier with known evidence for outcome correctness.

## Case structure

```json
[
  {
    "id": "warehouse-account-incident",
    "input": {
      "text": "Investigate the duplicate material issue for account acct-test-001 and reproduce it in staging.",
      "account_id": "acct-test-001"
    },
    "expected_trajectory": {
      "capability": "bug_analysis",
      "account_id": "acct-test-001",
      "required_domains": ["warehouse", "inventory"],
      "required_repositories": ["acme/warehouse-execution", "acme/inventory-ledger"],
      "required_focus_repositories": ["acme/inventory-ledger"],
      "forbidden_focus_repositories": ["acme/warehouse-supervisor-ui"],
      "required_tools": ["admin_lookup", "splunk_search", "jira_search", "reproduce_backend", "codebot"],
      "tool_repositories": {"reproduce_backend": ["acme/inventory-ledger"], "codebot": ["acme/inventory-ledger"]},
      "dependencies": [{"before": "reproduce_backend", "after": "codebot"}],
      "forbidden_tools": ["jira_create"]
    }
  }
]
```

Use known stable test accounts only; keep credentials and real production records out of cases. Expectations should be strict enough to catch a wrong route without overfitting to task IDs, worker completion order, or one model's wording. Add one case per materially different paved path rather than one case per repo.

## Validate the suite

Run cases against the intended harness with the trajectory CLI. This uses mocked tools:

```sh
.venv/bin/on-call-trajectory run-suite /path/to/trajectory_cases.json \\
  --harness /path/to/team/harness
```

Inspect every failure tag. Fix stale names in the case or artifact when the expected route is wrong; change planner behavior only when the case reflects the intended team workflow. Keep an outcome evaluator or human-reviewed evidence set for correctness claims that the trajectory evaluator cannot establish.
