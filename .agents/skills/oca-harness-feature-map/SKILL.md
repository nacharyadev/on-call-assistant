---
name: oca-harness-feature-map
description: Build or refine OCA's feature map across repositories, components, changed-file paths, owners, consumers, and regression tests.
---

# Prepare the OCA feature map

Create or update `feature-map.json` at the harness root. Read `team/team-artifact.json` first so every feature references known domain and repo IDs. Use `examples/supply_chain/harness/feature-map.json` as the multi-repo example and `examples/agent_harness/feature-map.json` as the empty template.

## Map features to implementation surfaces

- Use one feature entry for a capability or customer-visible flow that can span multiple domains and repos. Avoid one entry per repository when those repos jointly implement one behavior.
- Set `name`, `repositories` (exact `owner/name` strings), and `ground_truth` (harness-relative PRD/decision paths). Add `domain` when one domain is the primary owner; it must match a team artifact domain.
- Add `components` for repo-specific roles. Each component must use a repo already listed on that feature and may include a short `role`, `path_globs`, and component-specific `tests`.
- Make glob patterns reflect actual source layout. Prefer patterns that identify feature code, not broad catchalls. Do not duplicate overlapping patterns for the same feature/repo unless they represent separate meaningful components.
- Add `owners`, `consumers`, and `tests` to support impact synthesis. Identify test paths from repository manifests or maintainers; do not infer a test exists from naming convention alone.
- Add `product_flows` to explain how a persona reaches the feature in the product and how each screen maps to frontend components, API calls, backend handlers, and emitted/consumed events. Use real route names and code symbols from the repos.
- When screenshots are available, map each one to its flow step with a harness-relative `path` and a useful `alt_text` describing the visible screen/state. The current OCA graph passes screenshot metadata as text; it does not load image bytes or perform visual analysis. A visual Codebot or browser integration must inspect the actual pixels.
- Use top-level `path_globs` only as a simpler per-repo mapping. The runtime supports it for legacy maps; prefer `components` for multi-layer flows.

## Required structure

The root object contains `features`, an array of unique feature objects. Example:

Each `product_flows` entry requires a stable `id`, `name`, `persona`, `success_state`, an `entrypoint` with `screen` and `frontend_repository`, and an ordered nonempty `steps` array. Each step requires `action`, `screen`, and `frontend_repository`; optional `api_calls` map HTTP `method` and `path` to a `backend_repository` and `code_symbol`. Optional `events` map an event name to its producer and consumer backend repos. A screenshot object has a harness-relative `path` and nonempty `alt_text`.

```json
{
  "features": [{
    "name": "operator material issue workflow",
    "domain": "warehouse",
    "repositories": ["acme/scanner-ui", "acme/warehouse-api", "acme/warehouse-execution", "acme/inventory-api", "acme/mes-ui"],
    "ground_truth": ["prds/material-issue.md", "decisions/adr-014-idempotency.md"],
    "components": [
      {"repository": "acme/scanner-ui", "role": "lot scan and retry UX", "path_globs": ["src/material-issue/**"], "tests": ["tests/material-issue.spec.ts"]},
      {"repository": "acme/warehouse-api", "role": "pick confirmation API", "path_globs": ["src/api/pick-confirmation/**"], "tests": ["tests/test_pick_confirmation_api.py"]},
      {"repository": "acme/warehouse-execution", "role": "issue event publisher", "path_globs": ["src/warehouse/material_issue*.py"]},
      {"repository": "acme/inventory-api", "role": "updated availability response", "path_globs": ["src/api/availability*.py"]},
      {"repository": "acme/mes-ui", "role": "work-order readiness display", "path_globs": ["src/work-orders/readiness/**"]}
    ],
    "product_flows": [{
      "id": "handheld-issue-confirmation",
      "name": "Confirm a material issue from an assigned pick",
      "persona": "Warehouse operator",
      "entrypoint": {"screen": "Assigned picks", "route": "/picks/assigned", "frontend_repository": "acme/scanner-ui", "screenshot": {"path": "ux/screenshots/assigned-picks.png", "alt_text": "Example only: seeded operator account showing the assigned pick list"}},
      "steps": [{
        "action": "Open a pick and scan its lot",
        "screen": "Pick confirmation",
        "route": "/picks/{pickId}/confirm",
        "frontend_repository": "acme/scanner-ui",
        "screenshot": {"path": "ux/screenshots/pick-confirmation.png", "alt_text": "Example only: pick confirmation screen with the lot scan field visible"},
        "api_calls": [{"method": "GET", "path": "/api/picks/{pickId}", "backend_repository": "acme/warehouse-api", "code_symbol": "get_pick"}]
      }, {
        "action": "Confirm the issued quantity",
        "screen": "Issue confirmation",
        "frontend_repository": "acme/scanner-ui",
        "api_calls": [{"method": "POST", "path": "/api/material-issues", "backend_repository": "acme/warehouse-api", "code_symbol": "confirm_material_issue"}]
      }],
      "events": [{"name": "MaterialIssued", "producer_repository": "acme/warehouse-execution", "consumer_repositories": ["acme/inventory-api"], "code_symbols": ["MaterialIssued", "event_id"]}],
      "success_state": "The pick is confirmed once and updated availability is visible to the shop-floor work-order flow."
    }],
    "owners": ["Warehouse Systems", "Inventory Platform", "Manufacturing Systems"],
    "consumers": ["Handheld operators", "Shop-floor operators"],
    "tests": ["tests/e2e/material-issue-workflow.spec.ts"]
  }]
}
```

The runtime uses Python `fnmatch.fnmatch` patterns to produce possible impact candidates, not confirmed runtime impact. In this matcher `*` also crosses `/`; do not assume Git-ignore or `pathlib.glob` semantics. When a component has `path_globs`, changed files outside them do not produce candidates for that component. An unpatterned component falls back to a repository-level candidate, so give every component explicit patterns when path-level precision is intended. If there is no component entry for a repo, legacy top-level `path_globs` are used.

`product_flows` are the customer-to-code crosswalk. Each flow starts at an entry screen and walks ordered user actions; screen steps map to frontend repo/routes and API calls map to backend repos/handlers. Event edges connect synchronous UX to asynchronous consumers. Screenshots are optional evidence on the entrypoint or a step, with `path` and descriptive `alt_text`; the paths in the example are illustrative and must be replaced with real assets. Sanitize captures to remove PII, account identifiers, and session tokens. OCA currently forwards this mapping and screenshot description, not the image itself; a visual Codebot or browser integration must inspect the image bytes.

Before finishing, verify every feature repo exists in the team artifact, each optional domain is known, component repos are members of the feature, paths exist or are confirmed by maintainers, and owners/consumers/tests are backed by supplied sources. Summarize uncertain links rather than filling gaps with assumptions.
