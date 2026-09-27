"""HTTP service with the live model and delayed, simulated worker tools."""

from __future__ import annotations

import os
from pathlib import Path

from on_call_assistant.agent.graph import create_graph
from on_call_assistant.api.service import create_app

from .simulated_tools import SimulatedTools


ROOT = Path(__file__).resolve().parent


def create_mock_app():
    token_file = ROOT.parents[1] / "runs" / "oca-api-token"
    token = os.environ.get("OCA_API_TOKEN") or (token_file.read_text().strip() if token_file.exists() else None)
    if not token:
        raise ValueError("Set OCA_API_TOKEN or create runs/oca-api-token before starting the mock service")
    delay_scale = float(os.environ.get("OCA_MOCK_DELAY_SCALE", "1"))
    graph = create_graph(ROOT / "harness", tools=SimulatedTools(delay_scale=delay_scale),
                         allow_jira_create=True)
    return create_app(ROOT / "harness", graph=graph, api_token=token)
