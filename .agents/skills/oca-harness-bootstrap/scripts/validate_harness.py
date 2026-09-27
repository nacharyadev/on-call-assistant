#!/usr/bin/env python3
"""Validate an OCA harness without starting a model or external tools."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any


def load_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"missing file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def linked_paths(artifact: dict[str, Any], features: dict[str, Any]) -> set[str]:
    paths = set()
    for domain in artifact.get("domains", []):
        paths.update(domain.get("prd_paths", []))
        paths.update(domain.get("decision_paths", []))
    for item in artifact.get("vocabulary", []):
        paths.update(item.get("source_paths", []))
    for feature in features.get("features", []):
        paths.update(feature.get("ground_truth", []))
        for flow in feature.get("product_flows", []):
            screenshots = [flow.get("entrypoint", {}).get("screenshot")]
            screenshots.extend(step.get("screenshot") for step in flow.get("steps", []))
            paths.update(item["path"] for item in screenshots if isinstance(item, dict) and item.get("path"))
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate an OCA harness")
    parser.add_argument("--harness", required=True, type=Path)
    parser.add_argument("--oca-root", type=Path,
                        help="OCA repository root when the package is not installed")
    args = parser.parse_args()
    harness = args.harness.resolve()
    artifact = load_object(harness / "team" / "team-artifact.json")
    features = load_object(harness / "feature-map.json")

    if args.oca_root:
        sys.path.insert(0, str(args.oca_root.resolve() / "src"))
    else:
        skill_root = Path(__file__).resolve().parents[4]
        if (skill_root / "src" / "on_call_assistant").is_dir():
            sys.path.insert(0, str(skill_root / "src"))
    from on_call_assistant.knowledge.catalog import build_repository_catalog

    catalog = build_repository_catalog(artifact, features, harness)
    missing = []
    for relative in sorted(linked_paths(artifact, features)):
        path = PurePosixPath(relative)
        target = (harness / Path(*path.parts)).resolve()
        if path.is_absolute() or ".." in path.parts or not target.is_relative_to(harness) or not target.is_file():
            missing.append(relative)
    if missing:
        raise ValueError(f"missing or unsafe linked harness paths: {', '.join(missing)}")

    trajectory = harness / "trajectory_cases.json"
    case_count = 0
    if trajectory.exists():
        cases = json.loads(trajectory.read_text(encoding="utf-8"))
        if not isinstance(cases, list):
            raise ValueError("trajectory_cases.json must contain an array")
        ids = [item.get("id") for item in cases if isinstance(item, dict)]
        if len(ids) != len(cases) or any(not isinstance(item, str) or not item for item in ids):
            raise ValueError("every trajectory case needs a nonempty string id")
        if len(set(ids)) != len(ids):
            raise ValueError("trajectory case IDs must be unique")
        case_count = len(cases)

    print(json.dumps({"valid": True, "harness": str(harness),
                      "domains": len(artifact.get("domains", [])),
                      "repositories": len(catalog),
                      "features": len(features.get("features", [])),
                      "trajectory_cases": case_count}))


if __name__ == "__main__":
    main()
