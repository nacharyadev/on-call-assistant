"""Durable, access-restricted observations for later isolated evaluation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..evaluation.report import capture_actual


_PRIVATE_KEY = re.compile(r"(?:^|[_-])(?:password|secret|token|api[_-]?key|authorization|cookie|ssn|email|phone)(?:$|[_-])", re.I)
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]+", re.I)
_ASSIGNMENT = re.compile(r"\b([A-Za-z_]*(?:password|secret|token|api[_-]?key)[A-Za-z_]*)\s*[:=]\s*[^\s,;]+", re.I)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def sanitize(value: Any) -> Any:
    """Remove common credentials and contact data before writing a capture."""
    if isinstance(value, dict):
        return {str(key): "[REDACTED]" if _PRIVATE_KEY.search(str(key)) else sanitize(item)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return _EMAIL.sub("[REDACTED_EMAIL]", _ASSIGNMENT.sub(
            lambda match: f"{match.group(1)}=[REDACTED]", _BEARER.sub("Bearer [REDACTED]", value)))
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return str(value)


def harness_fingerprint(harness_dir: Path) -> str | None:
    if not harness_dir.is_dir():
        return None
    digest = hashlib.sha256()
    for path in sorted(harness_dir.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"harness contains a symlink: {path}")
        if path.is_file():
            digest.update(str(path.relative_to(harness_dir)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FlowCaptureStore:
    def __init__(self, directory: str | Path, harness_dir: str | Path):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.directory, 0o700)
        harness = Path(harness_dir).resolve()
        if not harness.is_dir():
            raise ValueError(f"flow capture requires an existing harness directory: {harness}")
        if self.directory.is_relative_to(harness):
            raise ValueError("flow capture directory cannot be inside the harness")
        self.harness_sha256 = harness_fingerprint(harness)
        self.harness_snapshot = None
        if self.harness_sha256:
            snapshots = self.directory / "harnesses"
            snapshots.mkdir(mode=0o700, exist_ok=True)
            os.chmod(snapshots, 0o700)
            target = snapshots / self.harness_sha256
            if not target.exists():
                staging = Path(tempfile.mkdtemp(prefix=".harness-", dir=snapshots))
                try:
                    copy = staging / "snapshot"
                    shutil.copytree(harness, copy)
                    if harness_fingerprint(copy) != self.harness_sha256:
                        raise RuntimeError("harness changed while creating flow capture snapshot")
                    for path in copy.rglob("*"):
                        os.chmod(path, 0o700 if path.is_dir() else 0o600)
                    try:
                        os.rename(copy, target)
                    except FileExistsError:
                        pass  # Another service process captured this version first.
                finally:
                    shutil.rmtree(staging)
            if harness_fingerprint(target) != self.harness_sha256:
                raise RuntimeError(f"captured harness snapshot is inconsistent: {target}")
            self.harness_snapshot = str(target.relative_to(self.directory))

    def write(self, request_id: str, *, submitted_at: str, request: dict[str, Any],
              status: str, state: dict[str, Any] | None = None,
              error: str | None = None, finished_at: str | None = None) -> None:
        if not re.fullmatch(r"[0-9a-f-]{36}", request_id):
            raise ValueError("request_id must be a UUID")
        state = state or {}
        record = {
            "schema_version": 1,
            "request_id": request_id,
            "submitted_at": submitted_at,
            "finished_at": finished_at,
            "status": status,
            "harness_sha256": self.harness_sha256,
            "harness_snapshot": self.harness_snapshot,
            "model": {"provider": os.environ.get("OCA_MODEL_PROVIDER"),
                      "name": os.environ.get("OCA_MODEL")},
            "input": request,
            "capability": state.get("capability") or request.get("capability"),
            "classification": state.get("classification"),
            "plan": state.get("plan"),
            "tasks": state.get("tasks", []),
            "results": state.get("results", []),
            "trace": state.get("trace", []),
            "answer": state.get("answer"),
            "policy_tokens": state.get("policy_tokens", 0),
            "observed_trajectory": capture_actual({**state, "answer": state.get("answer") or {}}) if state else None,
            "error": error,
        }
        encoded = (json.dumps(sanitize(record), ensure_ascii=False, sort_keys=True, default=str) + "\n").encode()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.directory, prefix=".flow-", suffix=".tmp",
                                             delete=False) as stream:
                temporary = Path(stream.name)
                os.chmod(temporary, 0o600)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.directory / f"{request_id}.json")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
