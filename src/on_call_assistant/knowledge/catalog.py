"""Validate and index the team's multi-repository harness.

Legacy string repository entries remain valid. Structured entries give the
planner enough topology to choose a service, UI, or shared library precisely.
"""
from __future__ import annotations

from typing import Any


REPOSITORY_KINDS = {"frontend", "backend", "shared", "infrastructure"}


def repository_name(entry: str | dict[str, Any]) -> str:
    name = entry if isinstance(entry, str) else entry.get("name") if isinstance(entry, dict) else None
    if not isinstance(name, str) or "/" not in name or not all(name.split("/", 1)):
        raise ValueError(f"invalid repository entry: {entry!r}")
    return name


def build_repository_catalog(artifact: dict[str, Any], features: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return repo metadata and fail early on inconsistent harness mappings."""
    catalog: dict[str, dict[str, Any]] = {}
    domains = artifact.get("domains", [])
    feature_items = features.get("features", [])
    if not isinstance(domains, list) or not isinstance(feature_items, list):
        raise ValueError("domains and features must be arrays")
    seen_domains: set[str] = set()
    for domain in domains:
        if not isinstance(domain, dict) or not isinstance(domain.get("id"), str):
            raise ValueError("each domain needs an id")
        domain_id = domain["id"]
        if domain_id in seen_domains:
            raise ValueError(f"duplicate domain: {domain_id}")
        seen_domains.add(domain_id)
        entries = domain.get("repositories", [])
        if not isinstance(entries, list):
            raise ValueError(f"repositories for {domain_id} must be an array")
        seen_here: set[str] = set()
        for entry in entries:
            name = repository_name(entry)
            if name in seen_here:
                raise ValueError(f"duplicate repository in {domain_id}: {name}")
            seen_here.add(name)
            details = dict(entry) if isinstance(entry, dict) else {"name": name}
            kind = details.get("kind")
            if kind is not None and kind not in REPOSITORY_KINDS:
                raise ValueError(f"invalid kind for {name}: {kind}")
            existing = catalog.get(name)
            if existing and any(existing.get(key) != details.get(key)
                                for key in ("kind", "responsibility", "depends_on")):
                raise ValueError(f"conflicting repository metadata: {name}")
            catalog.setdefault(name, {**details, "domains": []})["domains"].append(domain_id)
    for name, details in catalog.items():
        dependencies = details.get("depends_on", [])
        if not isinstance(dependencies, list) or any(dep not in catalog or dep == name for dep in dependencies):
            raise ValueError(f"unknown or self repository dependency for {name}")
    seen_features: set[str] = set()
    for feature in feature_items:
        if not isinstance(feature, dict) or not isinstance(feature.get("name"), str):
            raise ValueError("each feature needs a name")
        name = feature["name"]
        if name in seen_features:
            raise ValueError(f"duplicate feature: {name}")
        seen_features.add(name)
        if feature.get("domain") is not None and feature["domain"] not in seen_domains:
            raise ValueError(f"feature {name} references an unknown domain")
        repositories = feature.get("repositories", [])
        if not isinstance(repositories, list) or any(repo not in catalog for repo in repositories):
            raise ValueError(f"feature {name} references an unknown repository")
        components = feature.get("components", [])
        if not isinstance(components, list) or any(
                not isinstance(component, dict) or component.get("repository") not in repositories
                for component in components):
            raise ValueError(f"feature {name} has a component outside its repositories")
    return catalog
