"""Small HTTP surface for submitting and inspecting OCA requests."""

from __future__ import annotations

import logging
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from ..agent.graph import create_graph
from ..common_config import COMMON_CONFIG
from .flow_capture import FlowCaptureStore, utc_now


log = logging.getLogger(__name__)


class OCARequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    account_id: str | None = None
    capability: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def create_app(harness_dir: str | Path | None = None, *, graph: Any | None = None,
               api_token: str | None = None, capture_dir: str | Path | None = None) -> FastAPI:
    token = api_token or os.environ.get("OCA_API_TOKEN")
    if not token:
        raise ValueError("OCA_API_TOKEN is required for the HTTP service")
    harness = Path(harness_dir or os.environ.get("OCA_HARNESS_DIR", "examples/agent_harness"))
    runtime = graph or create_graph(harness, allow_jira_create=os.environ.get("OCA_ALLOW_JIRA_CREATE") == "1")
    capture_location = capture_dir
    if capture_location is None and COMMON_CONFIG.capture_live_flows:
        capture_location = COMMON_CONFIG.flow_capture_dir
    captures = FlowCaptureStore(capture_location, harness) if capture_location else None
    executor = ThreadPoolExecutor(max_workers=int(os.environ.get("OCA_REQUEST_WORKERS", "4")))
    requests: dict[str, Future] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        executor.shutdown(wait=True)

    app = FastAPI(title="On-Call Assistant", version="0.1.0", lifespan=lifespan)

    def authenticate(authorization: str | None = Header(default=None)) -> None:
        if not authorization or not secrets.compare_digest(authorization, f"Bearer {token}"):
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.post("/requests", status_code=202, dependencies=[Depends(authenticate)])
    def submit(payload: OCARequest) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        submitted_at = utc_now()
        config = {"configurable": {"thread_id": request_id}}
        request = payload.model_dump(exclude_none=True, exclude={"capability"})
        if captures:
            try:
                captures.write(request_id, submitted_at=submitted_at,
                               request={**request, "capability": payload.capability} if payload.capability else request,
                               status="queued")
            except OSError as exc:
                log.exception("Could not capture queued request %s", request_id)
                raise HTTPException(status_code=503, detail="flow capture unavailable") from exc
        future = executor.submit(
            runtime.invoke, {"request": request, "capability": payload.capability or ""}, config
        )
        requests[request_id] = future
        if captures:
            def capture_completion(done: Future) -> None:
                try:
                    error = done.exception()
                    if error:
                        try:
                            state = runtime.get_state(config).values or {}
                        except Exception:
                            state = {}
                    else:
                        state = done.result() or {}
                    captures.write(
                        request_id, submitted_at=submitted_at,
                        request={**request, "capability": payload.capability} if payload.capability else request,
                        status="failed" if error else "completed", state=state,
                        error=str(error) if error else None, finished_at=utc_now(),
                    )
                except Exception:
                    log.exception("Could not capture completed request %s", request_id)
            future.add_done_callback(capture_completion)
        return {"request_id": request_id, "status": "queued"}

    @app.get("/requests/{request_id}", dependencies=[Depends(authenticate)])
    def status(request_id: str) -> dict[str, Any]:
        future = requests.get(request_id)
        if future is None:
            raise HTTPException(status_code=404, detail="request not found")
        snapshot = runtime.get_state({"configurable": {"thread_id": request_id}})
        state = snapshot.values
        if future.done() and future.exception():
            return {"request_id": request_id, "status": "failed", "error": str(future.exception()),
                    "tasks": state.get("tasks", []), "trace": state.get("trace", [])}
        lifecycle = "completed" if future.done() else "running" if state else "queued"
        task_list = state.get("tasks", [])
        return {"request_id": request_id, "answer": state.get("answer"),
                "tasks": task_list, "trace": state.get("trace", []),
                "progress": {"total": len(task_list), "completed": sum(task["status"] == "completed" for task in task_list)},
                "policy_tokens": state.get("policy_tokens", 0), "status": lifecycle}

    return app
