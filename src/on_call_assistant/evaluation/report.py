"""Compact, self-contained reports for expected and observed graph trajectories."""

from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .trajectory import DEFAULT_NODES


def capture_actual(state: dict[str, Any]) -> dict[str, Any]:
    """Keep the route and answer summary, without copying worker payloads or logs."""
    tasks = state.get("tasks", [])
    by_id = {task["id"]: task for task in tasks}
    routing = state.get("answer", {}).get("routing", {})
    waves = []
    for entry in state.get("trace", []):
        if entry.get("node") == "dispatch" and entry.get("ready"):
            waves.append([{"id": task_id, "tool": by_id[task_id]["tool"],
                           "repository": by_id[task_id].get("arguments", {}).get("repository")}
                          for task_id in entry["ready"] if task_id in by_id])
    return {
        "capability": state.get("capability"),
        "domains": routing.get("domains", []),
        "features": routing.get("features", []),
        "repositories": routing.get("repositories", []),
        "focus_repositories": routing.get("focus_repositories", []),
        "tools": [entry.get("tool") for entry in state.get("trace", []) if entry.get("node") == "worker"],
        "executed_task_ids": [entry.get("task_id") for entry in state.get("trace", [])
                              if entry.get("node") == "worker"],
        "tasks": [{"id": task.get("id"), "tool": task.get("tool"),
                   "repository": task.get("arguments", {}).get("repository"),
                   "account_id": task.get("arguments", {}).get("account_id")
                   if task.get("tool") in {"admin_lookup", "splunk_search"} else None,
                   "depends_on": task.get("depends_on", []), "status": task.get("status")}
                  for task in tasks],
        "waves": waves,
        "nodes": [entry.get("node") for entry in state.get("trace", [])],
        "summary": state.get("answer", {}).get("summary", ""),
    }


def write_reports(records: list[dict[str, Any]], *, json_path: Path | None = None,
                  html_path: Path | None = None) -> None:
    if json_path is not None:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    if html_path is not None:
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(render_html(records), encoding="utf-8")


def _safe(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _tags(values: list[Any], *, empty: str = "Any") -> str:
    if not values:
        return f'<span class="empty">{_safe(empty)}</span>'
    return "".join(f'<span class="tag">{_safe(value)}</span>' for value in values)


def _row(label: str, expected: list[Any], actual: list[Any], *, optional: bool = False) -> str:
    return (f'<div class="compare-row"><div class="row-label">{_safe(label)}</div>'
            f'<div class="row-value">{_tags(expected, empty="Any" if optional else "None")}</div>'
            f'<div class="row-value">{_tags(actual, empty="Unavailable")}</div></div>')


def _expected_values(expected: dict[str, Any], required: str, exact: str | None = None,
                     forbidden: str | None = None) -> list[str]:
    values = [f"required · {item}" for item in expected.get(required, [])]
    if exact and exact in expected:
        values += [f"exact · {item}" for item in expected[exact]] or ["exact · none"]
    if forbidden:
        values += [f"forbidden · {item}" for item in expected.get(forbidden, [])]
    return values


def _case_view(record: dict[str, Any], index: int) -> str:
    expected = record["expected_trajectory"]
    actual = record.get("actual") or {}
    verdict = record["verdict"]
    passed = verdict.get("reward") == 1.0
    failures = verdict.get("failure_tags", [])
    case_id = record["id"]
    tasks = actual.get("tasks", [])
    executed_ids = set(actual.get("executed_task_ids", []))
    actual_tool_repos = [f"{item['tool']} → {item['repository']}" for item in tasks
                         if item.get("repository") and item["id"] in executed_ids]
    task_by_id = {item["id"]: item for item in tasks}
    actual_dependencies = [f"{task_by_id[dependency]['tool']} → {item['tool']}" for item in tasks
                           for dependency in item.get("depends_on", []) if dependency in task_by_id]
    expected_tool_repos = [f"{tool} → {repo}" for tool, repos in expected.get("tool_repositories", {}).items()
                           for repo in repos]
    expected_dependencies = [f"{item['before']} → {item['after']}" for item in expected.get("dependencies", [])]
    waves = [" + ".join(item["tool"] for item in wave) for wave in actual.get("waves", [])]
    expected_waves = ["required · " + " + ".join(group) for group in expected.get("parallel_tools", [])]
    expected_waves += ["exact · " + " + ".join(group) for group in expected.get("exact_parallel_tools", [])]
    expected_nodes = expected.get("required_nodes", DEFAULT_NODES)
    checks = verdict.get("checks", [])
    checks_view = "".join(f'<span class="check {"ok" if item["passed"] else "bad"}">'
                          f'{"✓" if item["passed"] else "×"} {_safe(item["name"])}</span>' for item in checks)
    task_rows = "".join(
        f'<tr><td><code>{_safe(item["id"])}</code></td><td>{_safe(item["tool"])}</td>'
        f'<td>{_safe(item.get("repository") or "—")}</td><td>{_safe(", ".join(item.get("depends_on", [])) or "—")}</td>'
        f'<td>{_safe(item.get("status") or "—")}</td></tr>' for item in tasks)
    rows = [
        _row("Capability", [expected["capability"]] if expected.get("capability") else [],
             [actual["capability"]] if actual.get("capability") else [], optional=True),
        _row("Domains", _expected_values(expected, "required_domains"), actual.get("domains", []), optional=True),
        _row("Features", _expected_values(expected, "required_features", "exact_features"),
             actual.get("features", []), optional=True),
        _row("Context repos", _expected_values(expected, "required_repositories"),
             actual.get("repositories", []), optional=True),
        _row("Worker repos", _expected_values(expected, "required_focus_repositories",
                                             "exact_focus_repositories", "forbidden_focus_repositories"),
             actual.get("focus_repositories", []), optional=True),
        _row("Tools", _expected_values(expected, "required_tools", "exact_tools", "forbidden_tools"),
             [f"{tool} ×{count}" if count > 1 else tool for tool, count in Counter(actual.get("tools", [])).items()],
             optional=True),
        _row("Tool → repo", expected_tool_repos, actual_tool_repos, optional=True),
        _row("Parallel waves", expected_waves, waves, optional=True),
        _row("Dependencies", expected_dependencies, actual_dependencies, optional=True),
        _row("Graph stages", expected_nodes, actual.get("nodes", []), optional=True),
    ]
    if expected.get("account_id"):
        account_ids = sorted({item["account_id"] for item in tasks if item.get("account_id")})
        rows.insert(1, _row("Account lookup", [expected["account_id"]], account_ids))
    error = verdict.get("error")
    error_view = f'<div class="error-box"><strong>Execution stopped</strong><span>{_safe(error)}</span></div>' if error else ""
    failures_view = (f'<div class="failure-line">Mismatch: {_tags(failures)}</div>' if failures else
                     '<div class="success-line">Every expected route check passed.</div>')
    summary = actual.get("summary", "")
    summary_view = f'<p class="answer-summary">{_safe(summary)}</p>' if summary else ""
    return f'''<section class="case" id="case-{index}">
      <div class="case-heading"><div><span class="eyebrow">CASE {index:02d} / {_safe(case_id)}</span>
        <h2>{_safe(case_id.replace("-", " "))}</h2></div>
        <span class="status {"pass" if passed else "fail"}">{"PASS" if passed else "FAIL"}</span></div>
      <p class="request">{_safe(record.get("request", ""))}</p>
      {error_view}{failures_view}
      <div class="compare-head"><span>Route dimension</span><span>Expected · case JSON</span><span>Actual · graph run</span></div>
      <div class="compare-grid">{"".join(rows)}</div>
      {summary_view}
      <details {"open" if not passed else ""}><summary>Checks and task list <span>{len(checks)} checks · {len(tasks)} tasks</span></summary>
        <div class="checks">{checks_view or '<span class="empty">No checks completed.</span>'}</div>
        <div class="table-wrap"><table><thead><tr><th>Task ID</th><th>Tool</th><th>Repository</th><th>Depends on</th><th>Status</th></tr></thead>
        <tbody>{task_rows or '<tr><td colspan="5">No tasks captured.</td></tr>'}</tbody></table></div>
      </details>
    </section>'''


def render_html(records: list[dict[str, Any]]) -> str:
    passed = sum(record["verdict"].get("reward") == 1.0 for record in records)
    failed = len(records) - passed
    nav = "".join(
        f'<a href="#case-{index}" class="nav-case"><span class="nav-dot {"pass" if record["verdict"].get("reward") == 1.0 else "fail"}"></span>'
        f'<span>{_safe(record["id"])}</span><b>{"PASS" if record["verdict"].get("reward") == 1.0 else "FAIL"}</b></a>'
        for index, record in enumerate(records, 1))
    cases = "".join(_case_view(record, index) for index, record in enumerate(records, 1))
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OCA trajectory report</title>
<style>
:root{{--ink:#152a2b;--muted:#607273;--paper:#f4f1e9;--panel:#fffcf5;--line:#d9ddd3;--teal:#137b67;--red:#bd503d;--gold:#dba044}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:"Avenir Next",Avenir,Georgia,serif;line-height:1.5}}
body:before{{content:"";position:fixed;inset:0;pointer-events:none;opacity:.28;background-image:radial-gradient(#82918a 0.5px,transparent 0.5px);background-size:7px 7px}}
a{{color:inherit}}.masthead{{background:var(--ink);color:#f6f2e8;padding:46px max(5vw,24px) 38px;position:relative;overflow:hidden}}
.masthead:after{{content:"";position:absolute;width:420px;height:420px;border:1px solid #6b8178;border-radius:50%;right:-80px;top:-250px;box-shadow:0 0 0 44px #ffffff09,0 0 0 88px #ffffff06}}
.eyebrow{{font:700 11px/1.3 ui-monospace,SFMono-Regular,monospace;letter-spacing:.16em;text-transform:uppercase;color:var(--gold)}}
h1{{font:normal clamp(42px,6vw,78px)/.98 Georgia,serif;letter-spacing:-.05em;margin:13px 0 18px;max-width:820px}}
.masthead p{{max-width:620px;color:#c3d1cb;margin:0;font-size:16px}}.stats{{display:flex;gap:28px;margin-top:35px;flex-wrap:wrap}}
.stat{{border-left:2px solid var(--gold);padding-left:13px;min-width:88px}}.stat strong{{display:block;font:normal 31px/1 Georgia,serif}}.stat span{{font:700 10px ui-monospace,monospace;letter-spacing:.12em;text-transform:uppercase;color:#aec0b9}}
.layout{{display:grid;grid-template-columns:250px minmax(0,1fr);gap:32px;max-width:1640px;margin:auto;padding:32px max(5vw,24px) 100px;position:relative}}
aside{{align-self:start;position:sticky;top:24px}}.aside-title{{font:700 11px ui-monospace,monospace;letter-spacing:.14em;color:var(--muted);text-transform:uppercase;margin:4px 0 12px}}
.nav-case{{display:flex;align-items:center;gap:10px;padding:10px 8px;border-bottom:1px solid var(--line);text-decoration:none;font-size:13px}}
.nav-case:hover,.nav-case:focus-visible{{background:#e8ece4;outline:none}}.nav-case span:nth-child(2){{flex:1;overflow-wrap:anywhere}}.nav-case b{{font:700 10px ui-monospace,monospace;color:var(--muted)}}
.nav-dot{{width:8px;height:8px;border-radius:50%;flex:none}}.nav-dot.pass{{background:var(--teal)}}.nav-dot.fail{{background:var(--red)}}
.aside-note{{font-size:12px;color:var(--muted);margin-top:22px;padding:12px;border:1px solid var(--line);background:#ffffff7a}}
main{{min-width:0}}.case{{background:var(--panel);border:1px solid var(--line);box-shadow:6px 6px 0 #c7cec440;margin-bottom:32px;scroll-margin-top:20px}}
.case-heading{{display:flex;justify-content:space-between;gap:20px;align-items:start;padding:28px 30px 12px}}h2{{font:normal clamp(26px,3vw,38px)/1.08 Georgia,serif;letter-spacing:-.03em;margin:8px 0 0;text-transform:capitalize}}
.status{{font:800 11px ui-monospace,monospace;letter-spacing:.12em;border:1px solid currentColor;padding:7px 11px}}.status.pass{{color:var(--teal);background:#e2f0e9}}.status.fail{{color:var(--red);background:#fae8e0}}
.request{{font-size:14px;color:#435556;margin:0 30px 22px;max-width:860px}}.failure-line,.success-line,.error-box{{margin:0 30px 20px;padding:12px 15px;font-size:13px}}
.failure-line,.error-box{{background:#fff0e8;border-left:3px solid var(--red)}}.success-line{{background:#e6f2eb;border-left:3px solid var(--teal);color:#225b50}}
.error-box{{display:flex;gap:12px;flex-wrap:wrap}}.failure-line .tag{{background:white;color:var(--red)}}
.compare-head,.compare-row{{display:grid;grid-template-columns:150px minmax(0,1fr) minmax(0,1fr);gap:0}}
.compare-head{{background:#e9eee7;border-block:1px solid var(--line);font:800 10px ui-monospace,monospace;letter-spacing:.12em;text-transform:uppercase;color:#536968}}
.compare-head span{{padding:11px 16px}}.compare-head span+span{{border-left:1px solid var(--line)}}
.compare-row{{border-bottom:1px solid #e8eae2;min-height:48px}}.compare-row:last-child{{border-bottom:0}}.compare-row>div{{padding:11px 16px}}.compare-row>div+div{{border-left:1px solid #e8eae2}}
.row-label{{font:700 11px/1.5 ui-monospace,monospace;color:#657775;text-transform:uppercase;letter-spacing:.04em}}.row-value{{display:flex;gap:5px;flex-wrap:wrap;align-content:start}}
.tag{{display:inline-block;background:#e9efea;border:1px solid #d5e0d8;border-radius:3px;color:#26433d;padding:3px 6px;font:600 11px/1.35 ui-monospace,SFMono-Regular,monospace;overflow-wrap:anywhere;max-width:100%}}
.empty{{font:italic 12px Georgia,serif;color:#93a19c}}.answer-summary{{margin:0;padding:22px 30px;border-top:1px solid var(--line);font-size:14px;max-width:950px}}
details{{border-top:1px solid var(--line);padding:0 30px 24px}}summary{{cursor:pointer;padding:17px 0;font:700 12px ui-monospace,monospace;text-transform:uppercase;letter-spacing:.08em}}summary span{{float:right;color:var(--muted);font-weight:400;text-transform:none;letter-spacing:0}}
.checks{{display:flex;gap:6px;flex-wrap:wrap;padding:3px 0 17px}}.check{{font:600 11px ui-monospace,monospace;padding:5px 7px;border-radius:3px}}.check.ok{{background:#e4f2e9;color:#176d55}}.check.bad{{background:#fae4dd;color:#a83e30}}
.table-wrap{{overflow:auto}}table{{width:100%;border-collapse:collapse;text-align:left;font-size:12px}}th{{font:700 10px ui-monospace,monospace;text-transform:uppercase;color:var(--muted);letter-spacing:.09em;background:#edf0e9}}th,td{{padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}}td code{{font-size:11px}}
@media(max-width:960px){{.layout{{display:block}}aside{{position:static;margin-bottom:28px}}.nav-case{{display:inline-flex;border:1px solid var(--line);margin:0 5px 7px 0;background:#fffaf1}}.aside-note{{max-width:600px}}}}
@media(max-width:640px){{.masthead{{padding:32px 20px}}.layout{{padding:22px 12px 70px}}.case-heading{{padding:20px 18px 10px}}.request{{margin:0 18px 18px}}.failure-line,.success-line,.error-box{{margin:0 18px 15px}}.compare-head,.compare-row{{grid-template-columns:88px minmax(0,1fr) minmax(0,1fr)}}.compare-head span,.compare-row>div{{padding:8px 6px}}.tag{{font-size:10px}}details{{padding:0 18px 18px}}.answer-summary{{padding:18px}}}}
</style></head><body>
<header class="masthead"><span class="eyebrow">OCA / ROUTE ASSURANCE</span><h1>Trajectory ledger</h1>
<p>Expected paths from case JSON, beside the route the graph actually took. Worker results are mocked in this suite.</p>
<div class="stats"><div class="stat"><strong>{len(records)}</strong><span>Cases</span></div><div class="stat"><strong>{passed}</strong><span>Passed</span></div><div class="stat"><strong>{failed}</strong><span>Needs review</span></div></div></header>
<div class="layout"><aside><div class="aside-title">Cases / jump to</div>{nav}
<p class="aside-note">“Any” means the case does not constrain that dimension. Actual data includes the final task list and dispatch waves; no raw customer or tool payloads are embedded.</p></aside>
<main>{cases}</main></div></body></html>'''
