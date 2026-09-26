"""Model interface and OpenAI-compatible implementation."""
from __future__ import annotations
import json
import os
from typing import Any, Protocol

class ModelPort(Protocol):
    def complete_json(self, system: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]: ...


class OpenAIModel:
    def __init__(self, model: str | None = None):
        from openai import OpenAI

        self.model = model or os.getenv("OCA_MODEL", "gpt-4.1-mini")
        self.client = OpenAI(base_url=os.getenv("OPENAI_BASE_URL") or None)

    def complete_json(self, system: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        result = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        )
        content = result.choices[0].message.content or "{}"
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("model response must be a JSON object")
        return parsed, result.usage.total_tokens if result.usage else 0
