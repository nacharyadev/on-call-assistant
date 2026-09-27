"""Shared service configuration checked into the application code."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class CommonConfig:
    capture_live_flows: bool = False
    flow_capture_dir: Path = PROJECT_ROOT / "runs" / "flow-captures"


COMMON_CONFIG = CommonConfig()
