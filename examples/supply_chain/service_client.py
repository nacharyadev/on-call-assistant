"""Submit one named supply-chain payload to either local OCA HTTP service."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]


def main() -> None:
    requests = json.loads((ROOT / "service_requests.json").read_text(encoding="utf-8"))
    parser = argparse.ArgumentParser(description="Submit a supply-chain OCA service request")
    parser.add_argument("case", choices=sorted(requests))
    parser.add_argument("--port", type=int, default=8001, help="8001 uses delayed mock tools; 8000 uses configured gateways")
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    token = (PROJECT / "runs" / "oca-api-token").read_text(encoding="utf-8").strip()
    base = f"http://127.0.0.1:{args.port}"
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=15) as client:
        response = client.post(f"{base}/requests", headers=headers, json=requests[args.case])
        response.raise_for_status()
        request_id = response.json()["request_id"]
        print(f"{args.case}: {request_id}", flush=True)
        if args.no_wait:
            return
        deadline = time.monotonic() + args.timeout
        last_status = None
        while time.monotonic() < deadline:
            response = client.get(f"{base}/requests/{request_id}", headers=headers)
            response.raise_for_status()
            state = response.json()
            status = state["status"]
            tasks = [(task["tool"], task["status"]) for task in state.get("tasks", [])]
            snapshot = (status, tuple(tasks))
            if snapshot != last_status:
                print(f"  {status}: {tasks}", flush=True)
                last_status = snapshot
            if status in {"completed", "failed"}:
                print(json.dumps({"request_id": request_id, "status": status,
                                  "summary": (state.get("answer") or {}).get("summary"),
                                  "tasks": tasks, "error": state.get("error")}, indent=2))
                raise SystemExit(0 if status == "completed" else 1)
            time.sleep(0.5)
    raise SystemExit(f"Timed out after {args.timeout}s; request ID: {request_id}")


if __name__ == "__main__":
    main()
