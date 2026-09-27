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

### Evaluate and connect real systems

Run `.venv/bin/python -m examples.supply_chain.run --live-model` to score the model's incident and release flows against recorded evidence. Run `.venv/bin/on-call-evolve examples/live.json` for the separate RRSI experiment loop; ordinary HTTP requests do not start RRSI. To connect team repositories and gateways, follow [agent setup](docs/agent.md) and the [production end-to-end guide](docs/production-e2e.md). See [validation](docs/validation.md) for the path to a real team benchmark.

Open the [architecture view](architecture.html) for the module and workflow overview.

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
