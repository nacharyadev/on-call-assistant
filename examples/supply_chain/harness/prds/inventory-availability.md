# Inventory availability contract

For a tenant, SKU, lot, and location, available quantity equals confirmed physical quantity minus active reservations and confirmed logical material issues. Delivery retries of the same event must not consume stock again. The inventory ledger is the source for available-to-promise queries used by sales allocation and manufacturing work-order start.

The incident fixture begins with 160 units of RM-AL-6061 in lot LOT-77 at WH-CLE. A single 80-unit material issue should leave 80 units available. A second work order requiring 80 units may start. An observed ledger balance of zero with 80 physical units remaining is a reconciliation failure.
