"""Read versioned team artifacts and prompts from a harness directory."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

def _document(root: Path, relative: str) -> str:
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_file() or target.is_symlink():
        return ""
    return target.read_text(encoding="utf-8")[:20_000]


def _load_json(root: Path, relative: str) -> dict[str, Any]:
    content = _document(root, relative)
    return json.loads(content) if content else {}
