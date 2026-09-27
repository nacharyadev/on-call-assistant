# On-call assistant

A LangGraph on-call assistant and a separate harness evolution loop for software engineering work. The agent classifies requests, plans repository-scoped tasks, runs workers, and reports evidence. The evolution loop measures changes to prompts, the team artifact, feature map, retrieval, and tool policy against versioned tasks.

This project is inspired by Peng Xia et al., [*RRSI: Regularized Recursive Self-Improvement of Agent Harnesses*](https://arxiv.org/abs/2609.24972), arXiv:2609.24972 (2026). The paper motivates the edit budget, proposal history, leakage screening, cost-aware selection, and held-out evaluation used here.

## Get started

Run these commands from the repository root after cloning or checking out the project:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[serve]'
```

### Run the recorded example

This exercises the LangGraph, parallel workers, backend replay, trajectory checks, and outcome verifier without a model key or external services:

```sh
.venv/bin/python -m examples.supply_chain.run
```

### Try the HTTP service with a live model and delayed mock tools

Copy `.env.example` to `.env` and replace the model key placeholder. The default configuration uses Anthropic; change `OCA_MODEL_PROVIDER` and `OCA_MODEL` together to use another installed LangChain provider. Create a local API token once, then start the demo service:

```sh
test -f .env || cp .env.example .env
mkdir -p runs
test -f runs/oca-api-token || openssl rand -hex 32 > runs/oca-api-token
chmod 600 runs/oca-api-token
.venv/bin/uvicorn examples.supply_chain.mock_service:create_mock_app --factory --host 127.0.0.1 --port 8001
```

In a second terminal, change to the same repository root and submit a request. The client prints the request ID, task progress, and final summary:

```sh
.venv/bin/python -m examples.supply_chain.service_client incident
.venv/bin/python -m examples.supply_chain.service_client feature
```

The seven exact JSON bodies, covering all six capabilities plus browser UX reproduction, are in [service_requests.json](examples/supply_chain/service_requests.json). The [supply-chain guide](examples/supply_chain/README.md) includes a `curl` example and mock delay settings. Mock Codebot and Jira creation complete their simulated tool calls but do not change a repository or create a real ticket.

To retain live flow evidence for later RRSI trials, set `capture_live_flows=True` in `src/on_call_assistant/common_config.py` and restart the service. `flow_capture_dir` in the same file controls the storage path. Each request produces a restricted JSON record with input, a versioned harness snapshot, classification, plan, tasks, tool observations, trace, answer, usage, and final status. Export completed flows as reviewable task drafts:

```sh
.venv/bin/python -m on_call_assistant.evaluation.captured_flows \
  runs/flow-captures runs/rrsi-task-drafts.json
```

Add independent `expected_trajectory` labels, split the drafts into evolve and held-out suites, and point an RRSI config at those files and the matching harness. The trial runner replays captured tool observations without contacting live systems. See [the capture workflow](docs/evolution.md#capturing-live-flows-for-isolated-trials).

For a new regression or previously untested path, copy the request and selected terminal or Splunk evidence into one case file and replay it immediately:

```sh
.venv/bin/on-call-trajectory replay-case \
  examples/supply_chain/manual_live_case.json \
  --harness examples/supply_chain/harness \
  --report-json runs/manual-live-case.json \
  --report-html runs/manual-live-case.html
```

The command reports which expected routing checks failed and writes a simple expected-versus-actual view. Once the case is useful, add it to the RRSI evolve suite; reserve separate cases for held-out evaluation.

### Evaluate and connect real systems

Run `.venv/bin/python -m examples.supply_chain.run --live-model` to score the model's incident and release flows against recorded evidence. Run `.venv/bin/on-call-evolve examples/live.json` for the separate RRSI experiment loop; ordinary HTTP requests do not start RRSI. To connect team repositories and gateways, follow [agent setup](docs/agent.md) and the [production end-to-end guide](docs/production-e2e.md). See [validation](docs/validation.md) for the path to a real team benchmark.

Open the [architecture view](architecture.html) for the module and workflow overview.

### Bootstrap a harness from local repositories

The repo-local [$oca-harness-bootstrap skill](.agents/skills/oca-harness-bootstrap/SKILL.md) builds a fresh harness or incrementally refreshes an existing one from multiple locally checked-out Git repositories. Start an agent session in this repository and give the skill the parent workspace, harness destination, and optional domain scope.

Generate a fresh harness for every discovered domain:

```text
Use $oca-harness-bootstrap to create a fresh harness at ./team-harness
from every Git repository under /path/to/team-workspace.
```

Generate a fresh harness for one domain when its repositories are known:

```text
Use $oca-harness-bootstrap to create a fresh inventory-domain harness at
./team-harness from these repositories:
- /path/to/team-workspace/inventory-ledger
- /path/to/team-workspace/inventory-api
- /path/to/team-workspace/inventory-ui
Include verified cross-repository dependencies and report missing consumers.
```

After changes merge, refresh the complete harness:

```text
Use $oca-harness-bootstrap to incrementally update every domain in
./team-harness from Git repositories under /path/to/team-workspace.
```

Refresh one or more domains while preserving unrelated mappings:

```text
Use $oca-harness-bootstrap to incrementally update the inventory, warehouse,
and manufacturing domains in ./team-harness from repositories under
/path/to/team-workspace.
```

The generated harness contains:

```text
team-harness/
  team/team-artifact.json     Domains, repositories, ownership, dependencies
  feature-map.json            Product flows and frontend/backend code paths
  discovery-report.json       Versioned source evidence and unresolved gaps
  trajectory_cases.json       Expected paved paths for agent evaluation
  prompts/                    Generic classifier, planner, and response policy
  prds/ decisions/ runbooks/  Concise source-grounded context
```

The skill scans CODEOWNERS, manifests, routes, API and event contracts, feature flags, tests, and engineering documents. It stores local repository paths, commit baselines, and scan deltas under the harness's ignored `.oca/` directory. Durable mappings in `discovery-report.json` use repository names, commits, and source-relative paths so the harness does not depend on one developer's checkout location.

Incremental runs compare the current repository commits with the last successfully validated baseline. The baseline advances only after structural and relevant trajectory checks pass. All-domain and selected-domain baselines are separate, and the skill refuses to advance from dirty repositories or when commits changed after inspection. This lets a scheduled job or a developer rerun the same skill after merges without silently marking unprocessed code as current.

Directory proximity is not treated as domain ownership. For a new selected domain, provide explicit repository paths when source and architecture material cannot establish the boundary. The skill records uncertain mappings as provisional instead of inventing repository relationships, owners, routes, or tests. Detailed evidence and update rules are in the [bootstrap contract](.agents/skills/oca-harness-bootstrap/references/bootstrap-contract.md).

## Codebase

```text
src/on_call_assistant/
  agent/          LangGraph, planning, state, safety, release impact
  knowledge/      team artifact, feature map, document loading
  integrations/   model and external tool clients
  api/            authenticated HTTP service
  evaluation/     trajectory verifier and CLI
  evolution/      RRSI search, scoring, selection
  cli.py          local agent entry point
```

The versioned harness under `examples/agent_harness` is an empty template for real team mappings. `examples/demo_harness` and `examples/demo.json` are synthetic fixtures for the evolution loop. `examples/live.json` runs the real graph with model calls and dry-run tools as an integration smoke test.

For a richer local exercise, [the supply-chain example](examples/supply_chain/README.md) runs an inventory, warehouse, and manufacturing incident through the graph with an executable backend fixture, recorded operational evidence, a three-repository release comparison, and strict trajectory plus outcome checks.

## Verify locally

```sh
.venv/bin/python -m unittest discover -s tests
PYTHONPATH=src .venv/bin/python -m on_call_assistant.evolution.cli examples/demo.json
```

The synthetic evolution score validates the plumbing, not the real assistant. Real validation needs your team artifacts, tool gateways, reproducible task environments, and independent verifiers for the six capabilities.
