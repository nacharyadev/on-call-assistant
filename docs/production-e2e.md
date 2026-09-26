# End-to-end test with team systems

Use this guide when connecting OCA to your team's model, repositories, Jira, admin, observability, Codebot, and application environments. The first live pass should use a staging tenant or read-only production access and synthetic or approved test records. OCA's GitHub tools only read data; Codebot and the reproducer are separate services and must be configured to work in isolated checkouts and runtimes.

## What is connected

OCA sends these calls through `HTTPTools`:

| Capability | OCA configuration | Request contract |
| --- | --- | --- |
| Recent commits, PR files, release compare | `GITHUB_TOKEN`, optional `GITHUB_API_URL` | GitHub REST API |
| Jira search and optional create | `JIRA_GATEWAY_URL` | `POST /execute`, JSON `{"tool":"jira_search","arguments":{...}}` |
| Customer/account snapshot | `ADMIN_GATEWAY_URL` | `POST /execute`, JSON `{"tool":"admin_lookup","arguments":{"account_id":"..."}}` |
| Logs and exceptions | `SPLUNK_GATEWAY_URL` | `POST /execute`, JSON `{"tool":"splunk_search","arguments":{"account_id":"...",...}}` |
| Backend or browser reproduction | `REPRODUCER_URL` | `POST /execute`, tool is `reproduce_backend` or `reproduce_browser` |
| Code implementation or analysis | `CODEBOT_URL` | `POST /tasks` with task arguments plus request, context, and dependency results |

The internal URLs are service base URLs; OCA appends `/execute` or `/tasks`. If `OCA_SERVICE_TOKEN` is set, OCA sends it as a bearer token to these gateways. GitHub uses its separate `GITHUB_TOKEN`. Gateways should return JSON with a stable shape that their team adapter understands; OCA wraps a successful `/execute` response as `{"status":"ok","data":<gateway JSON>}`. Unconfigured internal tools return `unavailable`; an unconfigured Codebot returns `stub`.

`POST /requests` and `GET /requests/{id}` are protected by `OCA_API_TOKEN`. Requests and LangGraph checkpoints currently live in process memory. Use one service instance for this test; before multi-instance or restart-safe production use, add durable checkpointing and persistent request tracking.

## 1. Build and review the team harness

Copy `examples/agent_harness` to a versioned location readable by the OCA service. Fill in the team artifact and feature map:

- Add each domain and all of its frontend, backend, shared, and infrastructure repos.
- Give repos their exact GitHub `owner/name`, responsibility, signals, dependencies, entrypoints, and verification targets.
- Map cross-repo features to component roles, paths, owners, consumers, and regression tests.
- Add current PRDs and architecture decisions. Keep customer records and credentials out of this harness; it is model context.
- Add reproduction profiles for the gateway to map to isolated staging services, seeded test accounts, and browser routes.

Start OCA with the harness to catch malformed repository and feature references before connecting live systems. The harness is supplied through `OCA_HARNESS_DIR` below.

## 2. Configure credentials and service URLs

Create the ignored `.env` from the template, then provide secrets through your team's secret manager or local environment. Do not commit `.env` or paste credentials into test requests.

```sh
cp .env.example .env
```

Set the provider and model (`OCA_MODEL_PROVIDER`, `OCA_MODEL`) plus its API key. For Anthropic, use `ANTHROPIC_API_KEY`; for OpenAI, use `OPENAI_API_KEY`. Add the workspace ID when your Anthropic workspace requires it. Then add the integrations you have deployed:

```dotenv
GITHUB_TOKEN=...
JIRA_GATEWAY_URL=https://your-jira-gateway
ADMIN_GATEWAY_URL=https://your-admin-gateway
SPLUNK_GATEWAY_URL=https://your-splunk-gateway
REPRODUCER_URL=https://your-reproducer
CODEBOT_URL=https://your-codebot
OCA_SERVICE_TOKEN=...
```

Keep `OCA_ALLOW_JIRA_CREATE` unset or `0` for the initial test. It is `0` by default. Enable it only after the Jira gateway is configured for a test project and the team is ready to allow OCA to create tickets. Admin and observability gateways should enforce read-only access and their own account-level authorization; the OCA bearer token only authenticates OCA to the gateway.

## 3. Start the service

From the repository root, install the serving extra if needed. Set an API token, use a single worker process for this in-memory run, and point OCA at the team harness:

```sh
.venv/bin/pip install -e '.[serve]'
export OCA_API_TOKEN='use-a-local-test-token'
export OCA_HARNESS_DIR='/absolute/path/to/team/harness'
export OCA_REQUEST_WORKERS=2
.venv/bin/uvicorn on_call_assistant.api.service:create_app --factory --host 127.0.0.1 --port 8000
```

For a shared test environment, terminate TLS at your approved ingress and restrict access to the service. Do not expose the development server directly to the public internet.

## 4. Exercise read-only integrations first

Use one known test account in a staging tenant, and a request that does not ask to create a Jira ticket, change code, deploy, or mutate customer data. Include the account identifier explicitly so the planner is expected to schedule admin and Splunk lookups. Replace the sample text and ID with an authorized test case:

```sh
curl -sS -H "Authorization: Bearer $OCA_API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"text":"Investigate staging inventory discrepancies for account YOUR_TEST_ACCOUNT. Check related Jira history, recent changes, and reproduce against the isolated staging service."}' \
  http://127.0.0.1:8000/requests
```

Copy the returned `request_id`, then poll status:

```sh
curl -sS -H "Authorization: Bearer $OCA_API_TOKEN" \
  http://127.0.0.1:8000/requests/YOUR_REQUEST_ID
```

Repeat until `status` is `completed` or `failed`. Check the final response and task list:

- `tasks` should show the expected tool, repository, dependencies, and final status for each planned task.
- `trace` should show safety guard, classifier, planner, context synthesis, dispatch waves, workers, merge, and response synthesis.
- Independent lookups should start in the same dispatch wave. A reproducer should wait for required account/log results. Codebot should receive selected repository context and its prerequisite results.
- `answer.evidence` should cite task IDs that exist in `tasks`; claims should match the returned tool results.
- `incomplete_tasks` should explain unavailable integrations, errors, blocked dependencies, or the Codebot stub. Do not count a `stub`, `unavailable`, `error`, or `blocked` task as completed work.

If a request is `failed`, inspect its `error` and trace. A planner repeatedly fails when the model cannot produce a valid route; an integration task can instead finish with a gateway error in the task outcome.

## 5. Test each capability with a known case

Run one approved case at a time and retain the request ID, sanitized response, task statuses, trace, and gateway correlation IDs. Use these request shapes and check the corresponding behavior:

1. **Bug analysis:** use a known staging exception. Expect admin/Splunk evidence when an account is named, Jira history when requested, and recent commits for the suspected repo. If reproduction is requested, check the replay inputs, app version, assertions, and output. Confirm the answer separates observed facts from a suspected cause.
2. **Bug fix:** request a fix for a seeded defect in a disposable branch. Confirm Codebot receives the selected repo, relevant context, and reproduction evidence. Review its patch and regression tests in the isolated checkout. This OCA service reports Codebot's result; it does not merge or deploy the patch.
3. **Feature:** choose one small feature spanning a frontend and backend. Confirm both component repos are selected, implementation workers can run in parallel where independent, and a cross-repo review or integration check depends on both results.
4. **PR review:** provide a test PR number and exact repo. Confirm `github_pr_files` is called for that repo before Codebot reviews the changed files and callers.
5. **Release impact:** compare two known tags in all expected repos. Confirm each `github_compare` task is planned, that comparisons can run in parallel, and changed paths map to candidate features, owners, consumers, and tests. A path match alone is not proof of runtime impact.
6. **Tech debt:** select an explicitly obsolete flag or dead code path. Confirm the agent finds every owning repo and asks Codebot to assess references and tests. Review the proposed removal manually before applying it.

For frontend reproduction, verify the reproducer starts the right app version and browser route, uses a seeded account, captures console/network errors, and records assertions and screenshots without sharing session tokens. For backend reproduction, verify the gateway pins the commit, starts dependent services, loads fixtures, and tears down the environment even after a timeout or failed assertion.

## 6. Check the paved paths before widening access

The trajectory suite currently uses mocked tools. Adapt cases to your domain and keep an independent expected outcome for each case. Run it to check classification, domains, focused repos, tool selection, dependencies, and parallel waves:

```sh
.venv/bin/on-call-trajectory run-suite /path/to/team/trajectory_cases.json \
  --harness "$OCA_HARNESS_DIR"
```

This command uses `DryRunTools`, so it does not test your live gateways. Live gateway behavior is checked by the end-to-end requests above. Keep both checks: correct routing does not prove the returned diagnosis or code change is correct. The supply-chain example is a local reference for the inventory, warehouse, manufacturing flow:

```sh
.venv/bin/python -m examples.supply_chain.run
.venv/bin/python -m examples.supply_chain.run --live-model
```

The second command uses the configured model but still uses recorded tools; it does not call production integrations.

## 7. Expand to production data in stages

After the staging cases pass, connect production read-only endpoints behind the same authenticated gateway contracts and test with an approved, low-risk account. Compare OCA's findings with the incident owner’s known answer. Check gateway authorization logs, request volume, model usage, task failures, latency, and whether customer data is being minimized in returned evidence. Set rate limits and operational alerts at the gateway and service ingress.

Keep Jira creation disabled until the test project and write path are approved. Keep code writes inside isolated branches/worktrees and require a human review before merge. Do not connect deployment or release controls to these tests. Move to durable state storage and run restart/concurrency tests before serving multiple processes or relying on request history after restarts.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Startup says a repository or feature is unknown | Fix repo names, feature references, or `depends_on` values in the harness. |
| Task says `unavailable` | The corresponding gateway URL or GitHub credential is missing from the service environment. |
| Task says `error` | Check the gateway response, auth, timeout, and correlation ID. OCA reports gateway errors in task results. |
| Task is `blocked` | A prerequisite failed; inspect that task before changing the planner. |
| Codebot says `stub` | Set `CODEBOT_URL` and implement/verify the `POST /tasks` contract. |
| Reproduction says unavailable or cannot start | Set `REPRODUCER_URL`; configure an isolated backend/browser profile and seed data in that gateway. |
| Release answer misses a feature/owner/test | Check feature components, repository path patterns, and the compare response's changed filenames. |
| Status disappears after restart | This version uses in-memory state; add a durable checkpointer and request store. |
