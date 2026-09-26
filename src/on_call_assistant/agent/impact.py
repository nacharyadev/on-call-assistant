"""Map changed files to candidate features for release impact analysis."""

from __future__ import annotations

from fnmatch import fnmatch
from typing import Any


def impact_candidates(tasks: list[dict[str, Any]], results: list[dict[str, Any]],
                      feature_map: dict[str, Any]) -> list[dict[str, Any]]:
    by_id = {task["id"]: task for task in tasks}
    candidates: list[dict[str, Any]] = []
    for result in results:
        task = by_id.get(result.get("task_id"))
        if not task or task["tool"] != "github_compare":
            continue
        repository = task["arguments"].get("repository")
        files = result.get("outcome", {}).get("data", {}).get("files", [])
        for file in files:
            filename = file.get("filename")
            if not isinstance(filename, str):
                continue
            for feature in feature_map.get("features", []):
                if repository not in feature.get("repositories", []):
                    continue
                components = [component for component in feature.get("components", [])
                              if component.get("repository") == repository]
                if not components:
                    components = [{"role": None,
                                   "path_globs": feature.get("path_globs", {}).get(repository, [])}]
                for component in components:
                    patterns = component.get("path_globs", [])
                    matched = [pattern for pattern in patterns if fnmatch(filename, pattern)]
                    if patterns and not matched:
                        continue
                    candidates.append({
                        "feature": feature.get("name"), "repository": repository,
                        "file": filename, "match": "path" if matched else "repository",
                        "component_role": component.get("role"),
                        "url": file.get("url"),
                        "owners": feature.get("owners", []),
                        "consumers": feature.get("consumers", []),
                        "tests": sorted(set(feature.get("tests", []) + component.get("tests", []))),
                        "evidence_task_id": result["task_id"],
                    })
    return candidates
