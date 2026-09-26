# On-call assistant

A LangGraph on-call assistant and a separate harness evolution loop for software engineering work. The agent classifies requests, plans repository-scoped tasks, runs workers, and reports evidence. The evolution loop measures changes to prompts, the team artifact, feature map, retrieval, and tool policy against versioned tasks.

This project is inspired by Peng Xia et al., [*RRSI: Regularized Recursive Self-Improvement of Agent Harnesses*](https://arxiv.org/abs/2609.24972), arXiv:2609.24972 (2026). The paper motivates the edit budget, proposal history, leakage screening, cost-aware selection, and held-out evaluation used here.

Open the [local architecture view](architecture.html), then use [agent setup](docs/agent.md) or the [evolution guide](docs/evolution.md) for the relevant workflow.
See [validation](docs/validation.md) for the path from local tests to a real team benchmark, and [migration](docs/migration.md) for the renamed imports and paths.

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

For a richer local exercise, [the supply-chain example](examples/supply_chain/README.md) runs an inventory, warehouse, and manufacturing incident through the graph with a real backend replay, recorded operational evidence, a three-repository release comparison, and strict trajectory plus outcome checks.

For Anthropic, replace `ANTHROPIC_API_KEY` in the ignored `.env` file (or copy `.env.example` to `.env` first). The LangChain model adapter reads it when you run from the repository root. Change `OCA_MODEL_PROVIDER` and `OCA_MODEL` to switch models. See [agent setup](docs/agent.md) for service configuration.

## Verify locally

```sh
.venv/bin/python -m unittest discover -s tests
PYTHONPATH=src .venv/bin/python -m on_call_assistant.evolution.cli examples/demo.json
```

The synthetic evolution score validates the plumbing, not the real assistant. Real validation needs your team artifacts, tool gateways, reproducible task environments, and independent verifiers for the six capabilities.

The previous `~/dev/rrsi-oncall` path and `rrsi_oncall` imports remain as temporary compatibility aliases while another session migrates to this layout. New code should use `~/dev/on-call-assistant` and `on_call_assistant`.
