# Manufacturing work-order start

MES starts a work order only when the inventory availability API reports at least the required raw material for the specified tenant, plant, SKU, and lot. A failed check returns `INSUFFICIENT_MATERIAL` and does not start production. The work-order decision must be traceable to the inventory balance and the material-issue event history.
