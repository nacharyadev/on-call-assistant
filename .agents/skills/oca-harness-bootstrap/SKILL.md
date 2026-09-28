---
name: oca-harness-bootstrap
description: Generate or incrementally refresh an OCA harness from multiple locally checked-out repositories, either across all domains or for selected domains. Use when bootstrapping team maps, feature maps, vocabulary, context, and trajectory cases from source code, or keeping an existing harness aligned with merged code changes.
---

# Bootstrap an OCA harness

Build a source-grounded harness from a local multi-repository workspace. Support four combinations without requiring a different workflow: fresh or incremental, across all domains or only named domains.

## Establish scope

Resolve these inputs from the request and workspace:

- Workspace containing the checked-out repositories, or an explicit list of repository paths.
- Harness destination.
- `fresh` when no trusted harness exists; otherwise `update`.
- All domains by default, or the exact selected domain IDs/names.

Do not treat directory proximity as proof that repositories share a domain. In a fresh selected-domain run, use explicit repository paths when the requested domain cannot be reliably identified from source or approved architecture material. Continue with verified repositories and report unresolved candidates rather than inventing membership.

Read [references/bootstrap-contract.md](references/bootstrap-contract.md) before changing a harness. Then run the inventory helper:

```sh
python3 .agents/skills/oca-harness-bootstrap/scripts/inventory_workspace.py \
  --workspace /path/to/workspace \
  --harness /path/to/harness \
  --mode update \
  --domain inventory
```

Use repeated `--repo` arguments instead of `--workspace` when the repositories do not share a parent. Omit `--domain` to process all domains. The helper writes its report under `<harness>/.oca/`; do not copy that directory into model context or version control. It does not advance the successful-scan baseline yet.

Read [the worked bootstrap and incremental-refresh example](references/end-to-end-example.md) before the first run. It shows how repository evidence becomes harness changes, how provisional gaps are reported, and when the commit baseline advances.

## Build or refresh

For a fresh harness, create the standard harness directories and start from the empty structures described by the sibling OCA skills. For an update, read the entire existing team artifact and feature map before applying scoped changes. Preserve stable IDs, human-authored decisions, and mappings whose sources have not changed.

Use the scan report to focus source inspection:

- Inspect all candidate repositories on a fresh run.
- On update, inspect changed paths and their known producers, consumers, API clients, event consumers, and shared schemas. A contract change can require updates outside the selected repository.
- If a selected domain has no source changes, still check whether changed cross-domain dependencies affect it.
- Treat dirty worktrees as provisional evidence and identify them in the report.

Read and apply the sibling skills when producing their corresponding artifacts:

1. [oca-harness-team-map](../oca-harness-team-map/SKILL.md) for domains, repositories, dependencies, ownership, entrypoints, and verification targets.
2. [oca-harness-feature-map](../oca-harness-feature-map/SKILL.md) for cross-repository features, product flows, APIs, events, path globs, owners, consumers, and tests.
3. [oca-harness-vocabulary](../oca-harness-vocabulary/SKILL.md) for business terms, aliases, identifiers, events, flags, and code symbols.
4. [oca-harness-context-docs](../oca-harness-context-docs/SKILL.md) for concise PRDs, decisions, runbooks, and reproduction notes supported by source material.
5. [oca-harness-trajectory-evals](../oca-harness-trajectory-evals/SKILL.md) for representative paved paths. Do not derive expected paths from the agent's current behavior.
6. [oca-harness-prompts](../oca-harness-prompts/SKILL.md) only when measured trajectory failures show a generic prompt problem. Do not encode domain facts in prompts.

For every material mapping, retain repository, commit, and source path evidence in `discovery-report.json`. Mark evidence as `verified` when the inspected source establishes the relationship and `provisional` when owner confirmation or another repository is still needed. Never use customer data, credentials, or production log payloads as durable harness knowledge.

## Incremental update rules

- Change only selected domains plus cross-domain references made invalid by verified source changes.
- Merge new signals, paths, symbols, and tests without duplicating existing values.
- Remove a mapping only when source proves it was deleted or superseded. Record the removal and evidence.
- Do not replace curated domain definitions or ubiquitous language solely from filename similarity.
- Update the harness snapshot and `discovery-report.json` even when the scan concludes that no semantic harness change is required.
- Keep the prior commit and current commit for each scanned repository so the next run can explain its delta.

## Finish

Run the structural validator:

```sh
python3 .agents/skills/oca-harness-bootstrap/scripts/validate_harness.py \
  --harness /path/to/harness
```

Run the relevant trajectory cases after structural validation. For a selected-domain update, run that domain's cases plus cases for affected consumers; for an all-domain update, run the full suite. Report:

- Harness files created or changed.
- Repositories and commit ranges inspected.
- Domains refreshed and cross-domain effects.
- Verified additions, updates, and removals.
- Provisional mappings and missing repositories or documents.
- Structural and trajectory validation results.

Only after the harness update and validations succeed, rerun the same inventory command with `--mode update --advance-state`. This records the reviewed commits for that exact domain scope. It refuses dirty repositories or commits that changed after the reviewed scan. A failed or interrupted bootstrap must not consume repository deltas. All-domain and selected-domain baselines are tracked separately.

Do not claim that the harness is current merely because repository commits were recorded. It is current only to the inspected commits and sources listed in `discovery-report.json`.
