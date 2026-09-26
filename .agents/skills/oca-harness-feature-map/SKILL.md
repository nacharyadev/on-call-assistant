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
- Use top-level `path_globs` only as a simpler per-repo mapping. The runtime supports it for legacy maps; prefer `components` for multi-layer flows.

## Required structure

The root object contains `features`, an array of unique feature objects. Example:

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
    "owners": ["Warehouse Systems", "Inventory Platform", "Manufacturing Systems"],
    "consumers": ["Handheld operators", "Shop-floor operators"],
    "tests": ["tests/e2e/material-issue-workflow.spec.ts"]
  }]
}
```

The runtime uses path matches to produce possible impact candidates, not confirmed runtime impact. When a component has `path_globs`, changed files outside them do not produce candidates for that component. An unpatterned component falls back to a repository-level candidate; if there is no component entry for a repo, legacy top-level `path_globs` are used. Keep this distinction in mind when choosing how broad a mapping should be.

Before finishing, verify every feature repo exists in the team artifact, each optional domain is known, component repos are members of the feature, paths exist or are confirmed by maintainers, and owners/consumers/tests are backed by supplied sources. Summarize uncertain links rather than filling gaps with assumptions.
