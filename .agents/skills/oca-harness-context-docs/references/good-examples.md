# Context document examples

These examples are deliberately concise. Replace every fact with evidence from the target team's source, decisions, and maintainers.

## PRD example

```markdown
# Inventory availability for work-order start

Status: Approved

Owner: Inventory Platform

Consumers: Manufacturing Execution, Production Planning

## User need

A production supervisor must know whether a work order has enough material before starting it. The decision must identify the tenant, plant, SKU, lot, required quantity, and balance used.

## Contract

Available quantity equals confirmed physical quantity minus active reservations and confirmed logical material issues. Re-delivery of the same `event_id` must not reduce availability twice. `delivery_id` identifies a transport attempt and is not a business deduplication key.

## Acceptance criteria

- A work order starts when availability is greater than or equal to its required quantity.
- A duplicate `MaterialIssued` event leaves the balance unchanged after its first successful application.
- A rejected start returns `INSUFFICIENT_MATERIAL` and records the balance and event-history correlation ID.
- The inventory contract test and MES work-order-start integration test pass.

## Dependencies

- Warehouse Execution publishes `MaterialIssued` with a stable `event_id`.
- Inventory Ledger applies the event atomically with its deduplication record.
- MES queries Inventory API before changing work-order state.

## Out of scope

Forecast inventory and substitution recommendations are not part of the start decision.

## Open questions

- Owner confirmation is still required for the retention period of processed event IDs.
```

## ADR example

```markdown
# ADR-014: Deduplicate material issues by business event identity

Status: Accepted

Date: 2026-06-12

Owner: Inventory Platform

## Context

The warehouse outbox provides at-least-once delivery. A retry creates a new `delivery_id`, while `event_id` remains stable for one logical material issue. Legacy messages do not always contain `request_id`.

## Decision

Inventory consumers persist `event_id` in the same transaction as the ledger mutation. A previously committed `event_id` is acknowledged without applying another quantity change. `delivery_id` and `request_id` remain diagnostic fields.

## Consequences

- Duplicate delivery is safe after a successful transaction.
- The processed-event table participates in ledger recovery and retention planning.
- Consumers must expose duplicate-event metrics without reporting them as failed material issues.

## Alternatives considered

- `delivery_id`: rejected because it changes on retry.
- `request_id`: rejected because it is absent from legacy events.
- Time-window deduplication: rejected because correctness would depend on retry timing.
```

## Reproduction runbook example

```markdown
# Replay a duplicate material issue

Status: Staging only

Repository: `northstar/inventory-ledger`

Profile: `duplicate_material_issue`

## Preconditions

- Use the seeded tenant `acct-test-inventory`; do not use a production account.
- Start Inventory Ledger and its disposable database at the commit under investigation.
- Load lot `LOT-TEST-77` with 160 units and no active reservations.

## Steps

1. Publish `MaterialIssued(event_id=evt-test-77, delivery_id=delivery-1, quantity=80)`.
2. Wait until availability becomes 80.
3. Publish the same `event_id` with `delivery_id=delivery-2`.
4. Query the ledger, processed-event table, availability API, and duplicate-event metric.

## Expected result

- Availability remains 80.
- The ledger contains one 80-unit material issue.
- The processed-event table contains one `evt-test-77` row.
- The duplicate metric increments once.

## Evidence to retain

Store the application commit, fixture version, event payload without credentials, correlation IDs, assertions, and relevant sanitized logs.

## Cleanup

Stop the disposable services and delete the seeded database.

## Escalation

Stop and notify Inventory Platform if the first delivery fails, the second delivery changes availability, or cleanup cannot remove the fixture.
```

The examples state observable contracts and verification. They do not claim that an incident hypothesis is an approved product rule, and they do not embed credentials or real customer records.
