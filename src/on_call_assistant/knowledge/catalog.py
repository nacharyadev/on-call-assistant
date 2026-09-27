"""Validate and index the team's multi-repository harness.

Legacy string repository entries remain valid. Structured entries give the
planner enough topology to choose a service, UI, or shared library precisely.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any


REPOSITORY_KINDS = {"frontend", "backend", "shared", "infrastructure"}
MERGED_REPOSITORY_LIST_FIELDS = {"signals", "depends_on", "entrypoints", "verification"}


def select_vocabulary(vocabulary: list[dict[str, Any]], domain_ids: list[str],
                      feature_names: list[str], repositories: list[str]) -> list[dict[str, Any]]:
    """Select global vocabulary and entries scoped to the chosen plan context."""
    selected = []
    scopes = (("domain_ids", set(domain_ids)), ("feature_names", set(feature_names)),
              ("repositories", set(repositories)))
    for entry in vocabulary:
        if all(not entry.get(field) or set(entry[field]).intersection(values)
               for field, values in scopes):
            selected.append(entry)
    return selected


def repository_name(entry: str | dict[str, Any]) -> str:
    name = entry if isinstance(entry, str) else entry.get("name") if isinstance(entry, dict) else None
    if not isinstance(name, str) or "/" not in name or not all(name.split("/", 1)):
        raise ValueError(f"invalid repository entry: {entry!r}")
    return name


def build_repository_catalog(artifact: dict[str, Any], features: dict[str, Any],
                            harness_root: Path | None = None) -> dict[str, dict[str, Any]]:
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
            for field in MERGED_REPOSITORY_LIST_FIELDS.intersection(details):
                value = details[field]
                if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                    raise ValueError(f"{field} for {name} must be an array of strings")
            if existing:
                for field, value in details.items():
                    if field in MERGED_REPOSITORY_LIST_FIELDS:
                        merged = existing.get(field, [])
                        existing[field] = merged + [item for item in value if item not in merged]
                    elif field != "name" and field != "domains":
                        if field in existing and existing[field] != value:
                            raise ValueError(f"conflicting repository metadata for {name}: {field}")
                        existing[field] = value
                existing["domains"].append(domain_id)
            else:
                catalog[name] = {**details, "domains": [domain_id]}
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
        flows = feature.get("product_flows", [])
        if not isinstance(flows, list):
            raise ValueError(f"product_flows for {name} must be an array")
        flow_ids: set[str] = set()
        for flow in flows:
            if (not isinstance(flow, dict) or not isinstance(flow.get("id"), str) or not flow["id"].strip()
                    or not isinstance(flow.get("name"), str) or not flow["name"].strip()
                    or not isinstance(flow.get("persona"), str) or not flow["persona"].strip()
                    or not isinstance(flow.get("success_state"), str) or not flow["success_state"].strip()):
                raise ValueError(f"each product flow for {name} needs id, name, persona, and success_state")
            flow_id = flow["id"]
            if flow_id in flow_ids:
                raise ValueError(f"duplicate product flow in {name}: {flow_id}")
            flow_ids.add(flow_id)
            entrypoint = flow.get("entrypoint")
            if not isinstance(entrypoint, dict) or not isinstance(entrypoint.get("screen"), str):
                raise ValueError(f"product flow {flow_id} needs an entry screen")
            frontend_repo = entrypoint.get("frontend_repository")
            if (not isinstance(frontend_repo, str) or frontend_repo not in repositories
                    or catalog[frontend_repo].get("kind") != "frontend"):
                raise ValueError(f"product flow {flow_id} entrypoint must reference a feature frontend repo")
            steps = flow.get("steps", [])
            if not isinstance(steps, list) or not steps:
                raise ValueError(f"product flow {flow_id} needs ordered steps")
            for step in steps:
                if (not isinstance(step, dict) or not isinstance(step.get("action"), str)
                        or not isinstance(step.get("screen"), str)):
                    raise ValueError(f"product flow {flow_id} steps need an action and screen")
                frontend_repo = step.get("frontend_repository")
                if (not isinstance(frontend_repo, str) or frontend_repo not in repositories
                        or catalog[frontend_repo].get("kind") != "frontend"):
                    raise ValueError(f"product flow {flow_id} step must reference a feature frontend repo")
                _validate_screenshot(step.get("screenshot"), flow_id)
                if harness_root is not None:
                    _validate_screenshot_asset(step.get("screenshot"), flow_id, harness_root)
                api_calls = step.get("api_calls", [])
                if not isinstance(api_calls, list):
                    raise ValueError(f"product flow {flow_id} api_calls must be an array")
                for api in api_calls:
                    if not isinstance(api, dict):
                        raise ValueError(f"product flow {flow_id} API calls must be objects")
                    backend_repo = api.get("backend_repository")
                    if (not isinstance(api.get("method"), str) or not api["method"].strip()
                            or not isinstance(api.get("path"), str) or not api["path"].strip()
                            or not isinstance(backend_repo, str) or backend_repo not in repositories
                            or catalog[backend_repo].get("kind") not in {"backend", "shared"}):
                        raise ValueError(f"product flow {flow_id} API call must reference a feature backend repo")
            _validate_screenshot(entrypoint.get("screenshot"), flow_id)
            if harness_root is not None:
                _validate_screenshot_asset(entrypoint.get("screenshot"), flow_id, harness_root)
            events = flow.get("events", [])
            if not isinstance(events, list):
                raise ValueError(f"product flow {flow_id} events must be an array")
            for event in events:
                if not isinstance(event, dict) or not isinstance(event.get("name"), str) or not event["name"].strip():
                    raise ValueError(f"product flow {flow_id} events need a name")
                producer = event.get("producer_repository")
                consumers = event.get("consumer_repositories", [])
                if (producer not in repositories or catalog[producer].get("kind") not in {"backend", "shared"}
                        or not isinstance(consumers, list)
                        or any(repo not in repositories or catalog[repo].get("kind") not in {"backend", "shared"}
                               for repo in consumers)):
                    raise ValueError(f"product flow {flow_id} event repositories must be feature backends")
    vocabulary = artifact.get("vocabulary", [])
    if not isinstance(vocabulary, list):
        raise ValueError("vocabulary must be an array")
    seen_terms: set[str] = set()
    vocabulary_list_fields = ("aliases", "domain_ids", "feature_names", "repositories", "code_symbols", "source_paths")
    for item in vocabulary:
        if not isinstance(item, dict) or not isinstance(item.get("term"), str) or not item["term"].strip():
            raise ValueError("each vocabulary entry needs a term")
        key = item["term"].casefold()
        if key in seen_terms:
            raise ValueError(f"duplicate vocabulary term: {item['term']}")
        seen_terms.add(key)
        if not isinstance(item.get("definition"), str) or not item["definition"].strip():
            raise ValueError(f"vocabulary term {item['term']} needs a definition")
        for field in vocabulary_list_fields:
            values = item.get(field, [])
            if not isinstance(values, list) or not all(isinstance(value, str) and value.strip() for value in values):
                raise ValueError(f"{field} for vocabulary term {item['term']} must be an array of strings")
        if any(domain not in seen_domains for domain in item.get("domain_ids", [])):
            raise ValueError(f"vocabulary term {item['term']} references an unknown domain")
        if any(repo not in catalog for repo in item.get("repositories", [])):
            raise ValueError(f"vocabulary term {item['term']} references an unknown repository")
        if any(feature not in seen_features for feature in item.get("feature_names", [])):
            raise ValueError(f"vocabulary term {item['term']} references an unknown feature")
    return catalog


def _validate_screenshot(screenshot: Any, flow_id: str) -> None:
    if screenshot is None:
        return
    if not isinstance(screenshot, dict):
        raise ValueError(f"product flow {flow_id} screenshot must be an object")
    path = screenshot.get("path")
    if not isinstance(path, str) or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
        raise ValueError(f"product flow {flow_id} screenshot path must be harness-relative")
    if not isinstance(screenshot.get("alt_text"), str) or not screenshot["alt_text"].strip():
        raise ValueError(f"product flow {flow_id} screenshot needs descriptive alt_text")


def _validate_screenshot_asset(screenshot: Any, flow_id: str, harness_root: Path) -> None:
    if screenshot is None:
        return
    path = harness_root.joinpath(*PurePosixPath(screenshot["path"]).parts)
    resolved = path.resolve()
    if (not resolved.is_relative_to(harness_root.resolve()) or path.is_symlink()
            or not resolved.is_file()):
        raise ValueError(f"product flow {flow_id} screenshot asset is missing or outside the harness")
