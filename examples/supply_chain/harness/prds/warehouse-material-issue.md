# Warehouse material issue

The warehouse confirms a pick once per logical material-issue event ID. It records the tenant, SKU, lot, work order, quantity, event ID, and delivery ID in an outbox message. The outbox may deliver the same event more than once after a timeout; delivery ID changes on retry while event ID remains stable. Consumers must tolerate at-least-once delivery.
