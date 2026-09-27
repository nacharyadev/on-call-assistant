---
name: oca-harness-vocabulary
description: Build or refine OCA's domain vocabulary so customer language, operational terms, and code symbols resolve consistently across teams and repositories.
---

# Prepare OCA's domain and code vocabulary

Add entries to the root `vocabulary` array in `team/team-artifact.json`. Read the domain definitions, feature map, source docs, and relevant code before assigning meanings. The planner receives this vocabulary; selected entries and their `source_paths` are also passed to Codebot and reproduction workers as context.

## Capture ubiquitous language

- Choose one canonical business term for each concept and explain it in one concise `definition`. Add customer-facing names, acronyms, legacy labels, and team slang in `aliases`.
- Map concepts to concrete code terms in `code_symbols`: event types, schema fields, API names, enum values, handlers, or feature flags. Preserve distinctions between similar-looking identifiers (for example `event_id`, `delivery_id`, and `request_id`) instead of treating them as synonyms.
- Scope terms with `domain_ids`, `feature_names`, and/or `repositories` when they are team-specific. Entries with no scope are global. When more than one scope field is present, an entry is included only when it matches every populated scope category.
- Add `source_paths` to the approved PRD, ADR, glossary, event schema, API spec, or code map that establishes the meaning. Paths are relative to the harness root and are loaded into request context.
- Prefer terms that help translate what a user says into a concrete feature and repo. Avoid generic words such as "status" unless the definition makes the team's exact state machine clear.
- Keep definitions stable and non-sensitive. Do not store customer names, account data, credentials, or raw incident logs as vocabulary.

## Required structure

Each vocabulary object requires a unique `term` and a nonempty `definition`. Optional arrays contain strings: `aliases`, `domain_ids`, `feature_names`, `repositories`, `code_symbols`, and `source_paths`.

```json
{
  "vocabulary": [
    {
      "term": "material issue",
      "definition": "Confirmation that stock physically left the warehouse; its logical event must reduce inventory availability once.",
      "aliases": ["goods issue", "material consumption"],
      "domain_ids": ["warehouse", "inventory", "manufacturing"],
      "feature_names": ["material issue and production consumption"],
      "repositories": ["northstar/warehouse-execution", "northstar/inventory-ledger", "northstar/manufacturing-execution"],
      "code_symbols": ["MaterialIssued", "event_id", "material_issue_consumer"],
      "source_paths": ["decisions/adr-014-material-issue-idempotency.md"]
    },
    {
      "term": "logical event identity",
      "definition": "Stable identity of one business event across retries; it is distinct from each delivery attempt and from an optional request correlation ID.",
      "aliases": ["event ID", "event key"],
      "repositories": ["northstar/warehouse-execution", "northstar/inventory-ledger"],
      "code_symbols": ["event_id", "delivery_id", "request_id"],
      "source_paths": ["decisions/adr-014-material-issue-idempotency.md"]
    }
  ]
}
```

Before finishing, verify every referenced domain, feature, and repository exists. Confirm each source path exists and supports the definition; do not infer a code symbol from a term's name. Keep different concepts as separate canonical entries even when teams often confuse them. Summarize any disputed or provisional definitions for domain-owner review.
