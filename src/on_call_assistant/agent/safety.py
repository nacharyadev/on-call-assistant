"""Redaction for tool observations before graph persistence."""
from __future__ import annotations
from typing import Any

def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        sensitive = {"password", "secret", "token", "api_key", "authorization", "cookie", "ssn", "email", "phone"}
        return {key: "[REDACTED]" if key.lower() in sensitive else _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value
