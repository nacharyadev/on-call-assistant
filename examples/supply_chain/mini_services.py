"""Small executable replay of an at-least-once material-issue delivery.

This is a deliberately faulty fixture, not a production implementation. The
warehouse deduplicates by event ID; the inventory consumer regressed to an
optional request ID and therefore applies a legacy scanner event twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field


ACCOUNT = "acct-aurora-07"
SKU = "RM-AL-6061"
LOT = "LOT-77"
EVENT_ID = "evt-mi-7842"


class MaterialIssue(BaseModel):
    event_id: str
    delivery_id: str
    request_id: str | None = None
    account_id: str
    sku: str
    lot: str
    work_order: str
    quantity: int = Field(gt=0)


class WorkOrderStart(BaseModel):
    account_id: str
    sku: str
    lot: str
    required_quantity: int = Field(gt=0)


@dataclass
class StockState:
    warehouse_physical: int = 160
    inventory_available: int = 160
    warehouse_events: set[str] = field(default_factory=set)
    inventory_events: set[str] = field(default_factory=set)


def create_app(*, dedupe_by_event_id: bool = False) -> FastAPI:
    state = StockState()
    app = FastAPI(title="Supply-chain replay")

    @app.post("/events/material-issued")
    def material_issued(event: MaterialIssue) -> dict:
        if (event.account_id, event.sku, event.lot) != (ACCOUNT, SKU, LOT):
            raise HTTPException(404, "unknown stock key")
        if event.event_id not in state.warehouse_events:
            state.warehouse_events.add(event.event_id)
            state.warehouse_physical -= event.quantity

        # Regression: request_id is absent on legacy scanner events. A retry
        # therefore bypasses this dedupe check and decrements the ledger again.
        key = event.event_id if dedupe_by_event_id else event.request_id
        if key is None or key not in state.inventory_events:
            state.inventory_available -= event.quantity
            if key is not None:
                state.inventory_events.add(key)
        return {"event_id": event.event_id, "delivery_id": event.delivery_id,
                "warehouse_physical": state.warehouse_physical,
                "inventory_available": state.inventory_available}

    @app.post("/work-orders/{work_order}/start")
    def start_work_order(work_order: str, request: WorkOrderStart) -> dict:
        if (request.account_id, request.sku, request.lot) != (ACCOUNT, SKU, LOT):
            raise HTTPException(404, "unknown stock key")
        if state.inventory_available < request.required_quantity:
            raise HTTPException(409, {"code": "INSUFFICIENT_MATERIAL",
                                      "work_order": work_order,
                                      "available": state.inventory_available,
                                      "required": request.required_quantity})
        return {"work_order": work_order, "status": "started",
                "available_at_start": state.inventory_available}

    return app


def replay_material_issue() -> dict:
    base = {"event_id": EVENT_ID, "request_id": None, "account_id": ACCOUNT,
            "sku": SKU, "lot": LOT, "work_order": "WO-4821", "quantity": 80}
    next_work_order = {"account_id": ACCOUNT, "sku": SKU, "lot": LOT,
                       "required_quantity": 80}

    def replay(dedupe_by_event_id: bool) -> dict:
        with TestClient(create_app(dedupe_by_event_id=dedupe_by_event_id)) as client:
            first = client.post("/events/material-issued", json={**base, "delivery_id": "delivery-1"})
            retry = client.post("/events/material-issued", json={**base, "delivery_id": "delivery-2"})
            start = client.post("/work-orders/WO-4822/start", json=next_work_order)
            return {"first": first.json(), "retry": retry.json(),
                    "work_order_http_status": start.status_code,
                    "work_order_response": start.json()}

    broken = replay(False)
    reference = replay(True)
    return {"event_id": EVENT_ID, "initial_quantity": 160, "issue_quantity": 80,
            "observed": broken, "reference_event_id_dedupe": reference,
            "bug_reproduced": broken["retry"]["inventory_available"] == 0
            and broken["retry"]["warehouse_physical"] == 80
            and broken["work_order_http_status"] == 409
            and reference["retry"]["inventory_available"] == 80
            and reference["work_order_http_status"] == 200}


app = create_app()
