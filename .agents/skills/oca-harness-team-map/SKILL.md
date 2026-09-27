---
name: oca-harness-team-map
description: Prepare or update an OCA team artifact that maps domains to frontend, backend, and shared repositories, owners, and source documents.
---

# Prepare the OCA team map

Create or update `team/team-artifact.json` in the team's harness. Use `examples/supply_chain/harness/team/team-artifact.json` for a populated multi-repository example and `examples/agent_harness/team/team-artifact.json` for the empty template.

## Gather and model

- Derive domain boundaries, repo names, ownership, dependencies, and operational tools from user-provided artifacts or verified repository metadata. Ask about important missing facts; do not invent repo names, owners, runtime relationships, or production tool behavior.
- Map each domain to every relevant frontend, backend, shared library, and infrastructure repo. A repo can belong to multiple domains only when its metadata is consistent.
- Describe runtime/contract dependencies with `depends_on`, but do not imply that a dependency automatically schedules a worker.
- Keep domain definitions and repository responsibilities specific enough to distinguish adjacent services. Use `signals` for terms and symptoms that route issues to a repo.
- Use repository names in GitHub `owner/name` form. Prefer structured repo entries; legacy string entries are accepted for existing harnesses.
- Point `prd_paths` and `decision_paths` only to documents present under the harness root. Use paths relative to that root.

## Required structure

The root JSON object contains `domains` (array) and may contain `name`, `snapshot`, `tools`, and `vocabulary`. Every domain has a unique `id`, a `definition`, and `repositories`. A structured repository has `name` and may include `kind` (`frontend`, `backend`, `shared`, or `infrastructure`), `responsibility`, `signals` (string array), `depends_on` (repo-name array), `entrypoints`, `verification`, and `reproduction_profile`. Domain entries may also include `owners`, `prd_paths`, and `decision_paths`. Use the `oca-harness-vocabulary` skill to prepare `vocabulary` terms, aliases, and code symbols.

Example:

```json
{
  "name": "Acme fulfillment platform",
  "snapshot": "2026-09-27",
  "domains": [{
    "id": "warehouse",
    "definition": "Lot picks, issue confirmation, and event delivery",
    "repositories": [
      {"name": "acme/scanner-ui", "kind": "frontend", "responsibility": "Lot scans and offline retries", "signals": ["scanner retry", "lot scan"], "depends_on": ["acme/warehouse-api"]},
      {"name": "acme/warehouse-api", "kind": "backend", "responsibility": "Pick confirmation API", "depends_on": ["acme/warehouse-execution"]},
      {"name": "acme/warehouse-execution", "kind": "backend", "responsibility": "Issue event publisher"}
    ],
    "owners": ["Warehouse Systems"],
    "prd_paths": ["prds/material-issue.md"],
    "decision_paths": ["decisions/adr-014-idempotency.md"]
  }],
  "tools": {"jira": "Incident history and planned work", "splunk": "Delivery and exception events"}
}
```

Before finishing, check that domain IDs and repository names are unique within each domain, every dependency names a repo in the catalog, every repo has a valid `kind` when present, and each document path exists. For repos repeated across domains, keep single-value metadata identical; OCA merges `signals`, `depends_on`, `entrypoints`, and `verification`, and rejects conflicting scalar metadata. OCA validates repository and feature references when it creates the graph; document links should be checked when authoring because missing files otherwise become empty context.

Do not include credentials, customer records, incident payloads, or secret URLs in the artifact. Use stable service descriptions and route-specific signals. Summarize the changes and call out any unverified mappings.
