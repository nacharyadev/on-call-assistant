"""Side-effect-free tool port used by trajectory evaluations."""

from __future__ import annotations

from typing import Any


class DryRunTools:
    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"status": "ok", "data": {"dry_run": True, "tool": name}}
