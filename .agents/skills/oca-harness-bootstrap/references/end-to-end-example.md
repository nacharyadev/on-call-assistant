# Worked bootstrap and refresh example

## Starting workspace

```text
team-workspace/
├── inventory-ledger/
├── inventory-api/
├── inventory-ui/
├── warehouse-execution/
├── warehouse-api/
├── scanner-ui/
├── manufacturing-execution/
└── mes-ui/
```

Request:

```text
Use $oca-harness-bootstrap to create a fresh harness at ./team-harness from every
Git repository under /path/to/team-workspace. Map inventory, warehouse, and
manufacturing product flows. Mark relationships as provisional when source does not
identify an owner or consumer.
```

## Source observations

The scan records facts such as:

- `scanner-ui/src/features/material-issue/routes.ts` declares `/picks/{pickId}/confirm`.
- Its API client calls `POST /api/picks/{pickId}/material-issue`.
- `warehouse-api` implements that route and calls the warehouse execution service.
- `warehouse-execution` publishes the versioned `MaterialIssued` schema.
- `inventory-ledger` consumes `MaterialIssued` and tests `event_id` idempotency.
- `manufacturing-execution` calls Inventory API before work-order start.
- CODEOWNERS identifies Warehouse Systems and Inventory Platform, but the MES owner is absent.

The skill should not infer the missing MES owner from the repository name.

## Resulting harness changes

`team/team-artifact.json` contains three domains and structured repository entries. `feature-map.json` contains one cross-domain material-issue flow from scanner route to API handler, event producer, inventory consumer, and MES consumer. Vocabulary distinguishes `event_id`, `delivery_id`, and `request_id`. The trajectory suite contains an account-scoped incident and a cross-repository release-impact case.

The versioned report includes evidence and the unresolved owner:

```json
{
  "schema_version": 1,
  "mode": "fresh",
  "scope": {"domains": ["inventory", "warehouse", "manufacturing"]},
  "repositories": [
    {
      "name": "northstar/inventory-ledger",
      "previous_commit": null,
      "commit": "abc123",
      "dirty": false,
      "inspected_paths": [
        "src/inventory/material_issue_consumer.py",
        "tests/test_material_issue_idempotency.py"
      ]
    }
  ],
  "changes": [
    {
      "artifact": "feature-map.json",
      "target": "operator material issue workflow",
      "change": "added event producer, inventory consumer, and idempotency test mapping",
      "evidence": [
        {
          "repository": "northstar/inventory-ledger",
          "commit": "abc123",
          "path": "src/inventory/material_issue_consumer.py"
        }
      ],
      "confidence": "verified"
    }
  ],
  "unresolved": [
    {
      "target": "manufacturing domain owner",
      "reason": "No CODEOWNERS entry or approved architecture source identifies the owner."
    }
  ]
}
```

After structural and trajectory validation pass, the skill advances the local `.oca` baseline for the all-domain scope.

## Incremental refresh

Later, `inventory-api` merges commit `def456`, adding `/availability/explain` and its contract test. The user requests:

```text
Use $oca-harness-bootstrap to incrementally update the inventory domain in
./team-harness from repositories under /path/to/team-workspace.
```

The inventory compares `abc123..def456`, inspects the changed handler, schema, client, and tests, and then follows known consumers into MES. It updates the inventory feature component, product-flow API call, code symbol, and regression test. It preserves unrelated warehouse routes and curated vocabulary.

If MES has not adopted the endpoint, the report records it as a potential consumer change rather than claiming the product flow already uses it. After selected-domain and affected-consumer trajectory cases pass, the skill advances only the inventory-domain baseline.

## Completion report

A useful final report is concrete:

```text
Updated domain: inventory
Inspected: inventory-api abc123..def456; manufacturing-execution 789abc
Changed: feature-map.json, discovery-report.json, trajectory_cases.json
Verified: explain endpoint, ExplainAvailability handler, contract test
Provisional: MES adoption pending a client change
Validation: structural pass; 4 inventory and consumer trajectory cases pass
Baseline: inventory scope advanced to def456
```
