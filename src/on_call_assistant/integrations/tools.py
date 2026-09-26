"""Explicit tool boundary for the on-call agent.

Third-party systems are configured separately. An unconfigured integration returns
an unavailable result, so a local graph cannot invent customer or code evidence.
"""

from __future__ import annotations

import os
import re
from typing import Any, Protocol
from urllib.parse import quote

import httpx


class ToolPort(Protocol):
    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class HTTPTools:
    """GitHub REST plus configurable internal service adapters.

    Internal adapters accept POST /execute with {tool, arguments}. Codebot uses
    POST /tasks. These small contracts can be replaced by real client adapters.
    """

    SERVICE_TOOLS = {
        "jira_search": "JIRA_GATEWAY_URL",
        "jira_create": "JIRA_GATEWAY_URL",
        "admin_lookup": "ADMIN_GATEWAY_URL",
        "splunk_search": "SPLUNK_GATEWAY_URL",
        "reproduce_backend": "REPRODUCER_URL",
        "reproduce_browser": "REPRODUCER_URL",
    }

    @staticmethod
    def _files(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
        remaining = 100_000
        summarized = []
        truncated = False
        for item in items:
            patch = item.get("patch")
            if isinstance(patch, str):
                clipped = patch[:remaining]
                remaining -= len(clipped)
                truncated |= len(clipped) < len(patch)
                patch = clipped or None
            summarized.append({"filename": item.get("filename"), "status": item.get("status"),
                               "patch": patch, "changes": item.get("changes"),
                               "url": item.get("blob_url")})
        return summarized, truncated

    def __init__(self, client: httpx.Client | None = None, env: dict[str, str] | None = None):
        self.client = client or httpx.Client(timeout=20)
        self.env = env if env is not None else os.environ

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "codebot":
            return self._codebot(arguments)
        if name.startswith("github_"):
            return self._github(name, arguments)
        env_key = self.SERVICE_TOOLS.get(name)
        if not env_key:
            return {"status": "error", "error": f"unknown tool: {name}"}
        base_url = self.env.get(env_key)
        if not base_url:
            return {"status": "unavailable", "tool": name, "reason": f"{env_key} is not configured"}
        try:
            response = self.client.post(
                f"{base_url.rstrip('/')}/execute",
                json={"tool": name, "arguments": arguments},
                headers=self._service_headers(),
            )
            response.raise_for_status()
            return {"status": "ok", "data": response.json()}
        except (httpx.HTTPError, ValueError) as exc:
            return {"status": "error", "tool": name, "error": str(exc)}

    def _service_headers(self) -> dict[str, str]:
        token = self.env.get("OCA_SERVICE_TOKEN")
        return {"Authorization": f"Bearer {token}"} if token else {}

    def _codebot(self, arguments: dict[str, Any]) -> dict[str, Any]:
        url = self.env.get("CODEBOT_URL")
        if not url:
            return {"status": "stub", "tool": "codebot", "message": "Codebot endpoint is not configured"}
        try:
            response = self.client.post(
                f"{url.rstrip('/')}/tasks", json=arguments,
                headers=self._service_headers(),
            )
            response.raise_for_status()
            return {"status": "ok", "data": response.json()}
        except (httpx.HTTPError, ValueError) as exc:
            return {"status": "error", "tool": "codebot", "error": str(exc)}

    def _github(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        repository = arguments.get("repository", "")
        if not isinstance(repository, str) or len(repository.split("/")) != 2:
            return {"status": "error", "error": "repository must be owner/name"}
        owner, repo = repository.split("/")
        if not all(part.replace("-", "").replace("_", "").replace(".", "").isalnum() for part in (owner, repo)):
            return {"status": "error", "error": "invalid repository name"}
        path = f"/repos/{owner}/{repo}"
        params: dict[str, Any] = {}
        if name == "github_recent_commits":
            path += "/commits"
            params = {"per_page": 20}
            if arguments.get("since"):
                params["since"] = arguments["since"]
        elif name == "github_pr_files":
            number = arguments.get("pr_number")
            if not isinstance(number, int) or number < 1:
                return {"status": "error", "error": "pr_number must be positive"}
            path += f"/pulls/{number}/files"
            params = {"per_page": 100}
        elif name == "github_compare":
            base, head = arguments.get("base"), arguments.get("head")
            if not all(isinstance(ref, str) and len(ref) <= 100 and
                       re.fullmatch(r"[A-Za-z0-9_./-]+", ref) and "..." not in ref
                       for ref in (base, head)):
                return {"status": "error", "error": "base and head must be safe ref names"}
            path += f"/compare/{quote(base, safe='')}...{quote(head, safe='')}"
        else:
            return {"status": "error", "error": f"unknown GitHub tool: {name}"}
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.env.get("GITHUB_TOKEN"):
            headers["Authorization"] = f"Bearer {self.env['GITHUB_TOKEN']}"
        try:
            url = f"{self.env.get('GITHUB_API_URL', 'https://api.github.com').rstrip('/')}{path}"
            if name == "github_pr_files":
                files = []
                for page in range(1, 31):
                    response = self.client.get(url, params={**params, "page": page}, headers=headers)
                    response.raise_for_status()
                    batch = response.json()
                    if not isinstance(batch, list):
                        raise ValueError("GitHub PR files response must be a list")
                    files.extend(batch)
                    if len(batch) < 100:
                        break
                data, patches_truncated = self._files(files)
                return {"status": "ok", "data": data,
                        "truncated": len(files) >= 3000 or patches_truncated}
            response = self.client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            if name == "github_recent_commits":
                data = [{"sha": item.get("sha"), "message": item.get("commit", {}).get("message"),
                         "url": item.get("html_url"), "date": item.get("commit", {}).get("committer", {}).get("date")}
                        for item in data]
            else:
                files, patches_truncated = self._files(data.get("files", []))
                truncated = len(files) >= 300 or patches_truncated
                data = {"files": files,
                        "comparison_url": data.get("html_url"),
                        "commits": [{"sha": item.get("sha"), "message": item.get("commit", {}).get("message")}
                                    for item in data.get("commits", [])]}
                return {"status": "ok", "data": data, "truncated": truncated}
            return {"status": "ok", "data": data}
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return {"status": "error", "tool": name, "error": str(exc)}
