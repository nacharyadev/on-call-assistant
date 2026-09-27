#!/usr/bin/env python3
"""Inventory local Git repositories and calculate deltas for harness refreshes."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


IGNORED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "vendor", "dist", "build",
    "target", ".next", ".cache", "coverage", "__pycache__", ".tox", ".mypy_cache",
}
EVIDENCE_NAMES = {
    "codeowners", "readme", "package.json", "pyproject.toml", "pom.xml", "build.gradle",
    "build.gradle.kts", "go.mod", "cargo.toml", "dockerfile", "docker-compose.yml",
    "docker-compose.yaml", "openapi.yaml", "openapi.yml", "openapi.json", "asyncapi.yaml",
    "asyncapi.yml", "schema.graphql", "buf.yaml", "catalog-info.yaml",
}
EVIDENCE_PARTS = re.compile(
    r"(?:^|/)(?:docs?|adr|decisions?|runbooks?|api|routes?|controllers?|handlers?|clients?|events?|schemas?|"
    r"proto|graphql|features?|flags?|tests?|e2e|integration|migrations?)(?:/|$)", re.I
)
SECRET_NAMES = re.compile(r"(?:^|/)(?:\.env(?:\.|$)|.*(?:secret|credential|private[_-]?key).*)(?:$|/)", re.I)


def run_git(repo: Path, *args: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args], text=True, capture_output=True, check=False,
    )
    if check and completed.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed in {repo}: {completed.stderr.strip()}")
    return completed.stdout.rstrip() if completed.returncode == 0 else ""


def is_repo(path: Path) -> bool:
    return bool(run_git(path, "rev-parse", "--show-toplevel", check=False))


def discover_repositories(workspace: Path, max_depth: int) -> list[Path]:
    workspace = workspace.resolve()
    found: set[Path] = set()
    for current, dirs, _files in os.walk(workspace):
        path = Path(current)
        depth = len(path.relative_to(workspace).parts)
        dirs[:] = [item for item in dirs if item not in IGNORED_DIRS and not item.startswith(".")]
        if is_repo(path):
            root = Path(run_git(path, "rev-parse", "--show-toplevel")).resolve()
            found.add(root)
            dirs[:] = []
            continue
        if depth >= max_depth:
            dirs[:] = []
    return sorted(found)


def canonical_name(repo: Path) -> str | None:
    remote = run_git(repo, "remote", "get-url", "origin", check=False)
    if not remote:
        return None
    cleaned = remote.removesuffix(".git").rstrip("/")
    match = re.search(r"(?:[:/])([^/:]+/[^/]+)$", cleaned)
    return match.group(1) if match else None


def interesting_paths(repo: Path, limit: int = 400) -> list[str]:
    paths = run_git(repo, "ls-files", "-co", "--exclude-standard", check=False).splitlines()
    selected = []
    for relative in paths:
        normalized = relative.replace("\\", "/")
        if SECRET_NAMES.search(normalized):
            continue
        path = Path(normalized)
        lower_name = path.name.lower()
        stem = path.stem.lower()
        if (lower_name in EVIDENCE_NAMES or stem in {"readme", "codeowners"}
                or EVIDENCE_PARTS.search(normalized)):
            selected.append(normalized)
        if len(selected) >= limit:
            break
    return selected


def changed_paths(repo: Path, previous: str | None, current: str, dirty: bool) -> tuple[str, list[str]]:
    if previous and previous != current:
        diff = run_git(repo, "diff", "--name-only", f"{previous}..{current}", check=False)
        if diff:
            return "commit_delta", sorted(set(diff.splitlines()))
        if run_git(repo, "cat-file", "-e", f"{previous}^{{commit}}", check=False) == "":
            return "full", []
    if dirty:
        status = run_git(repo, "status", "--porcelain=v1", "--untracked-files=all", check=False)
        paths = [line[3:].split(" -> ")[-1] for line in status.splitlines() if len(line) > 3]
        return "working_tree", sorted(set(paths))
    if previous == current:
        return "unchanged", []
    return "full", []


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def local_path(repo: Path, workspace: Path | None) -> str:
    if workspace:
        try:
            return str(repo.relative_to(workspace)) or "."
        except ValueError:
            pass
    return str(repo)


def main() -> None:
    parser = argparse.ArgumentParser(description="Inventory repositories for an OCA harness bootstrap")
    parser.add_argument("--workspace", type=Path, help="parent directory containing Git repositories")
    parser.add_argument("--repo", action="append", default=[], type=Path,
                        help="explicit repository path; repeat for multiple repositories")
    parser.add_argument("--harness", required=True, type=Path)
    parser.add_argument("--mode", choices=("fresh", "update"), default="update")
    parser.add_argument("--domain", action="append", default=[], help="selected domain; repeat as needed")
    parser.add_argument("--max-depth", type=int, default=2)
    parser.add_argument("--output", type=Path, help="local scan report path")
    parser.add_argument("--state", type=Path, help="local previous-commit state path")
    parser.add_argument("--advance-state", action="store_true",
                        help="record current commits after a successful harness update")
    args = parser.parse_args()

    if not args.workspace and not args.repo:
        parser.error("provide --workspace or at least one --repo")
    if args.max_depth < 0:
        parser.error("--max-depth must be nonnegative")
    workspace = args.workspace.resolve() if args.workspace else None
    if workspace and not workspace.is_dir():
        parser.error(f"workspace does not exist: {workspace}")

    harness = args.harness.resolve()
    artifact_exists = (harness / "team" / "team-artifact.json").exists()
    if args.mode == "fresh" and artifact_exists:
        parser.error("fresh mode requires a new harness destination; use --mode update")
    if args.mode == "update" and not artifact_exists:
        parser.error("update mode requires an existing team/team-artifact.json; use --mode fresh")

    local_dir = harness / ".oca"
    output = (args.output or local_dir / "workspace-scan.json").resolve()
    state_path = (args.state or local_dir / "source-state.json").resolve()
    approved_report = None
    if args.advance_state:
        if not output.is_file():
            parser.error("--advance-state requires the previously reviewed scan report")
        approved_report = json.loads(output.read_text(encoding="utf-8"))
    previous_state: dict[str, Any] = {}
    if state_path.is_file():
        previous_state = json.loads(state_path.read_text(encoding="utf-8"))
    scope_key = "domains:" + ",".join(sorted(set(args.domain))) if args.domain else "all"
    scopes = previous_state.get("scopes", {})
    if not scopes and previous_state.get("repositories"):
        scopes = {"all": previous_state["repositories"]}  # schema v1 compatibility
    previous_repositories = scopes.get(scope_key, scopes.get("all", []))
    previous_by_name = {item.get("name") or item.get("path"): item
                        for item in previous_repositories}

    repositories = {path.resolve() for path in args.repo}
    if workspace:
        repositories.update(discover_repositories(workspace, args.max_depth))
    invalid = [str(path) for path in repositories if not path.is_dir() or not is_repo(path)]
    if invalid:
        parser.error(f"not Git repositories: {', '.join(sorted(invalid))}")

    records = []
    next_state = []
    for repo in sorted(repositories):
        name = canonical_name(repo)
        path_label = local_path(repo, workspace)
        key = name or path_label
        prior = previous_by_name.get(key, {})
        current = run_git(repo, "rev-parse", "HEAD")
        dirty = bool(run_git(repo, "status", "--porcelain=v1", "--untracked-files=normal", check=False))
        scan_scope, changed = changed_paths(repo, prior.get("commit"), current, dirty)
        record = {
            "name": name,
            "path": str(repo),
            "workspace_path": path_label,
            "commit": current,
            "previous_commit": prior.get("commit"),
            "branch": run_git(repo, "branch", "--show-current", check=False) or None,
            "dirty": dirty,
            "scan_scope": scan_scope,
            "changed_paths": changed,
            "evidence_candidates": interesting_paths(repo),
        }
        if name is None:
            record["unresolved"] = "origin remote does not identify an owner/name repository"
        records.append(record)
        next_state.append({"name": name, "path": path_label, "commit": current})

    generated_at = datetime.now(timezone.utc).isoformat()
    report = {
        "schema_version": 1,
        "generated_at": generated_at,
        "mode": args.mode,
        "workspace": str(workspace) if workspace else None,
        "harness": str(harness),
        "requested_domains": sorted(set(args.domain)),
        "repositories": records,
    }
    if args.advance_state:
        if any(item["dirty"] for item in records):
            parser.error("cannot advance state from dirty repositories; commit or discard local changes first")
        approved = {(item.get("name") or item["path"]): item["commit"]
                    for item in approved_report.get("repositories", [])}
        current = {(item.get("name") or item["path"]): item["commit"] for item in records}
        if approved != current or sorted(approved_report.get("requested_domains", [])) != sorted(set(args.domain)):
            parser.error("repositories or commits changed after the reviewed scan; run and review inventory again")
    atomic_json(output, report)
    if args.advance_state:
        next_scopes = dict(scopes)
        next_scopes[scope_key] = next_state
        state = {"schema_version": 2, "generated_at": generated_at, "scopes": next_scopes}
        atomic_json(state_path, state)
    local_dir.mkdir(parents=True, exist_ok=True)
    (local_dir / ".gitignore").write_text("*\n", encoding="utf-8")
    print(json.dumps({"report": str(output),
                      "state": str(state_path) if args.advance_state else None,
                      "state_advanced": args.advance_state,
                      "repositories": len(records),
                      "changed": sum(item["scan_scope"] != "unchanged" for item in records),
                      "domains": sorted(set(args.domain)) or ["all"]}))


if __name__ == "__main__":
    main()
