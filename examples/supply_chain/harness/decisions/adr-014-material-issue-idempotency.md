# ADR-014: material issue identity

The warehouse outbox provides at-least-once delivery. `event_id` is the stable identity of the business event. `delivery_id` changes on each transport attempt. `request_id` may be absent on legacy scanner messages and must not be used as the sole deduplication key. Inventory consumers must persist processed `event_id` values atomically with the ledger change. This decision applies to warehouse material issue and manufacturing consumption flows.
