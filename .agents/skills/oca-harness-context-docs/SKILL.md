---
name: oca-harness-context-docs
description: Prepare concise, source-grounded PRDs, architecture decisions, runbooks, or reproduction notes for OCA's team harness.
---

# Prepare OCA context documents

Create or update documents under the harness root, usually `prds/`, `decisions/`, or `runbooks/`. Link each document from the relevant domain's `prd_paths` or `decision_paths`, or from a feature's `ground_truth` in the harness map.

## Write usable context

- Base statements on the source material the user provides, repository behavior, approved system docs, or verified engineering decisions. Mark unresolved questions as open; do not turn a suggestion or incident hypothesis into an approved contract.
- Make the intended reader's job easier: describe observable behavior, invariants, dependencies, owners, failure behavior, and ways to verify the contract.
- For PRDs, distinguish user need, scope, acceptance criteria, dependencies, rollout assumptions, and out-of-scope work.
- For decisions, record status (proposed, accepted, superseded), context, decision, consequences, alternatives, owner, and date. Preserve previous decisions as historical records instead of silently rewriting what was agreed.
- For runbooks or reproduction notes, identify the service/repo, safe test environment, exact setup and inputs, expected outputs, cleanup behavior, and escalation condition. Never add production credentials or real customer payloads.
- Keep the document focused and within the loader's 20,000-character read limit. Prefer links/paths to large datasets over copying them into model context.

## File and link structure

Use stable descriptive paths such as `prds/material-issue.md`, `decisions/adr-014-idempotency.md`, and `runbooks/replay-material-issue.md`. Paths stored in JSON are relative to the harness root, not the repository root. Use plain Markdown with meaningful headings. Do not store a second copy of the same contract under another filename.

Before finishing, confirm every linked file exists under the harness root and the JSON paths match exactly. Report which claims came from provided sources and which remain open. If creating an initial template from incomplete information, label it `Draft` and leave factual fields explicitly unresolved instead of making up details.
