"""Provider-neutral JSON model port backed by LangChain chat models."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol


class ModelPort(Protocol):
    def complete_json(self, system: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]: ...


CLASSIFIER_SCHEMA = {
    "title": "OCAClassification",
    "type": "object",
    "properties": {
        "capability": {"type": "string", "enum": [
            "bug_analysis", "bug_fix", "feature", "pr_review", "release_impact", "tech_debt", "general",
        ]},
        "reason": {"type": "string"},
        "account_id": {"type": "string"},
    },
    "required": ["capability", "reason"],
    "additionalProperties": False,
}


class LangChainModel:
    """Keep graph nodes independent of the selected LangChain provider."""

    DEFAULT_MODELS = {"anthropic": "claude-sonnet-5", "openai": "gpt-4.1-mini"}

    def __init__(self, model: str | None = None, *, provider: str | None = None,
                 client: Any | None = None):
        self.provider = (provider or os.getenv("OCA_MODEL_PROVIDER", "openai")).strip().lower()
        self.model = model or os.getenv("OCA_MODEL") or self.DEFAULT_MODELS.get(self.provider)
        if not self.model:
            raise ValueError(f"Set OCA_MODEL for provider {self.provider}")
        if client is not None:
            self.client = client
            return
        if self.provider == "anthropic":
            key = os.getenv("ANTHROPIC_API_KEY", "")
            if not key or key.startswith("replace-with-"):
                raise ValueError("Set ANTHROPIC_API_KEY in .env or the environment before using Anthropic")
        from langchain.chat_models import init_chat_model

        options: dict[str, Any] = {}
        if self.provider in {"anthropic", "openai"}:
            options.update(timeout=float(os.getenv("OCA_MODEL_TIMEOUT_SECONDS", "120")), max_retries=0)
        if self.provider == "anthropic":
            options["max_tokens"] = int(os.getenv("OCA_MAX_OUTPUT_TOKENS", "8192"))
            workspace_id = os.getenv("ANTHROPIC_WORKSPACE_ID", "")
            if workspace_id and not workspace_id.startswith("replace-with-"):
                options["default_headers"] = {"anthropic-workspace-id": workspace_id}
        if self.provider == "openai" and os.getenv("OPENAI_BASE_URL"):
            options["base_url"] = os.environ["OPENAI_BASE_URL"]
        self.client = init_chat_model(self.model, model_provider=self.provider, **options)
        if self.provider == "openai":
            self.client = self.client.bind(response_format={"type": "json_object"})

    def complete_json(self, system: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        messages = [
            ("system", system + "\nReturn only a valid JSON object, with no Markdown fences or preamble."),
            ("human", json.dumps(payload, ensure_ascii=False)),
        ]
        if self.provider == "anthropic" and set(payload) == {"request"} and hasattr(self.client, "with_structured_output"):
            output = self.client.with_structured_output(
                CLASSIFIER_SCHEMA, method="json_schema", include_raw=True,
            ).invoke(messages)
            if output["parsing_error"] is not None or not isinstance(output["parsed"], dict):
                raise ValueError("classifier returned invalid structured output")
            usage = output["raw"].usage_metadata or {}
            return output["parsed"], int(usage.get("total_tokens", 0))
        tokens_used = 0
        for attempt in range(2):
            response = self.client.invoke(messages)
            usage = response.usage_metadata or {}
            tokens_used += int(usage.get("total_tokens", 0))
            if response.response_metadata.get("stop_reason") == "max_tokens":
                raise ValueError("model response was truncated; increase OCA_MAX_OUTPUT_TOKENS")
            try:
                parsed = json.loads(response.text)
            except json.JSONDecodeError as exc:
                if attempt == 1:
                    raise ValueError("model returned invalid JSON after 2 attempts") from exc
                messages.append(("human", "The previous response was not parseable JSON. Return one complete JSON object only."))
                continue
            if not isinstance(parsed, dict):
                raise ValueError("model response must be a JSON object")
            return parsed, tokens_used
        raise AssertionError("unreachable model retry state")


class OpenAIModel(LangChainModel):
    """Compatibility name for callers that explicitly select OpenAI."""

    def __init__(self, model: str | None = None, *, client: Any | None = None):
        super().__init__(model, provider="openai", client=client)


class AnthropicModel(LangChainModel):
    """Compatibility name for callers that explicitly select Anthropic."""

    def __init__(self, model: str | None = None, *, client: Any | None = None):
        super().__init__(model, provider="anthropic", client=client)


def create_model() -> ModelPort:
    from dotenv import load_dotenv

    for path in (Path.cwd() / ".env", Path(__file__).resolve().parents[3] / ".env"):
        if path.is_file():
            load_dotenv(dotenv_path=path, override=False)
            break
    return LangChainModel()
