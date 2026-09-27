"""Convert captured service flows into reviewable RRSI task drafts."""

from __future__ import annotations

import argparse
import copy
import json
import os
import threading
from pathlib import Path
from typing import Any


class RecordedFlowTools:
    """Replay captured observations only when a candidate makes the same tool call."""

    def __init__(self, observations: list[dict[str, Any]]):
        self.remaining = copy.deepcopy(observations)
        self.lock = threading.Lock()

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            for index, observation in enumerate(self.remaining):
                expected = observation["arguments"]
                if observation["tool"] == name and all(arguments.get(key) == value
                                                         for key, value in expected.items()):
                    return self.remaining.pop(index)["outcome"]
        return {"status": "unavailable", "error": "no matching recorded observation"}


def draft_task(record: dict[str, Any]) -> dict[str, Any]:
    if record.get("status") != "completed" or not record.get("capability"):
        raise ValueError("only completed, classified captures can become task drafts")
    outcomes = {result["task_id"]: result["outcome"] for result in record.get("results", [])}
    observations = [
        {"tool": task["tool"], "arguments": task.get("arguments", {}), "outcome": outcomes[task["id"]]}
        for task in record.get("tasks", []) if task.get("id") in outcomes
    ]
    request = {key: value for key, value in record["input"].items() if key != "capability"}
    task = {
        "id": f"captured-{record['request_id']}",
        "capability": record["capability"],
        "input": request,
        "recorded_tools": observations,
        "capture": {"request_id": record["request_id"],
                    "harness_sha256": record.get("harness_sha256"),
                    "harness_snapshot": record.get("harness_snapshot"),
                    "observed_trajectory": record.get("observed_trajectory"),
                    "answer": record.get("answer")},
    }
    domains = (record.get("plan") or {}).get("domain_ids") or []
    if len(domains) == 1:
        task["domain"] = domains[0]
    return task


def export_drafts(capture_dir: Path, output: Path) -> int:
    drafts = []
    for path in sorted(capture_dir.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("status") == "completed" and record.get("capability"):
            drafts.append(draft_task(record))
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(drafts, stream, indent=2)
        stream.write("\n")
    return len(drafts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export captured flows as RRSI task drafts")
    parser.add_argument("capture_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(f"Exported {export_drafts(args.capture_dir, args.output)} task drafts to {args.output}")


if __name__ == "__main__":
    main()
