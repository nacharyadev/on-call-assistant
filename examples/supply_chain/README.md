# Supply-chain on-call example

This is a **fictitious but executable** Northstar account incident spanning inventory, warehouse management, and manufacturing. The account, repositories, Jira ticket, commit, and Git URLs are recorded fixtures. No external credentials or services are needed for the default run.

## Incident

`acct-aurora-07` has 160 units of `RM-AL-6061`, lot `LOT-77`, before work order `WO-4821` issues 80 units. The warehouse confirms the issue once and retains 80 physical units. Its outbox delivers the same logical `event_id` twice after a timeout. The inventory consumer uses optional `request_id` as its dedupe key, so a legacy scanner message with no request ID decrements the ledger twice: **160 → 80 → 0**. MES then rejects `WO-4822`, which needs the remaining 80 units.

The example makes OCA retrieve an account snapshot, exception logs, a related Jira issue, and recent commits in parallel. The backend reproducer runs a small FastAPI service twice: once with the faulty dedupe rule and once with the `event_id` rule from the ADR. Codebot receives the evidence and returns an explicit stub status, so OCA does not claim a patch was made.

The companion release request compares `v3.7.0` and `v3.8.0` across the inventory ledger, warehouse execution, and manufacturing execution repositories. The feature map connects changed files to possible owners, consumers, and tests. These are impact candidates, not proof of a regression.

## Run

From the repository root:

```sh
.venv/bin/python -m examples.supply_chain.run
.venv/bin/python -m examples.supply_chain.run --case account-material-issue --json
.venv/bin/python -m unittest discover -s tests
```

The default run uses a deterministic fixture model and recorded tools. It exercises the actual LangGraph, parallel workers, task dependencies, checkpoints, context loading, and response path. It checks both the trajectory and an independent outcome verifier. The verifier checks the replayed stock values, duplicate event deliveries, MES response, source evidence, release path matches, and the reported Codebot stub. Tests also remove a log delivery or a changed file and confirm that the outcome check fails even when the trajectory still passes.

To test the same requests with Anthropic while retaining recorded tools, put your key in the ignored `.env` file at the repository root (copy `.env.example` if needed):

```sh
.venv/bin/python -m examples.supply_chain.run --live-model
```

This live-model run evaluates classification, planning, and synthesis against the recorded incident. It may fail the strict checks; those failures identify a concrete prompt, routing, or evidence problem. It still does not call production admin, Splunk, Jira, GitHub, Codebot, or browser services.

For a local Ollama model with its OpenAI-compatible endpoint:

```sh
OPENAI_BASE_URL=http://127.0.0.1:11434/v1 OPENAI_API_KEY=ollama \
  OCA_MODEL=qwen2.5:14b-instruct .venv/bin/python -m examples.supply_chain.run --live-model
```

The CLI prints each case's progress to stderr. Planner and answer validation can request up to two corrections from the model. A failed trajectory is reported as a failure; recorded tool results are never replaced with model-generated evidence.
Model calls time out after 120 seconds by default; set `OCA_MODEL_TIMEOUT_SECONDS` to change that limit.

## Files

| File | Purpose |
| --- | --- |
| `harness/team/team-artifact.json` | Three domains and five owning repositories |
| `harness/feature-map.json` | Cross-repo features, path patterns, owners, consumers, tests |
| `harness/prds/`, `harness/decisions/` | Stock and work-order contracts plus the idempotency decision |
| `recorded_tools.json` | Account, logs, Jira, commit, and release-diff responses |
| `mini_services.py` | Executable faulty backend and reference replay |
| `cases.json` | Public requests and hidden trajectory/outcome expectations |
| `fixtures.py` | Deterministic model and recorded tool port |
| `verifier.py` | Independent outcome checks |
| `run.py` | CLI for fixture and live-model runs |

To turn this into a team benchmark, replace fixture repositories and records with versioned exports, isolate a real checkout and app runtime for reproduction, add resolved incidents across all six capabilities, and keep held-out cases separate from prompt tuning.
