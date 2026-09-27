from __future__ import annotations

import difflib
import hashlib
import json
import math
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


COMPONENTS = frozenset({
    "prompt", "control_flow", "config", "output_plumbing", "context_mgmt",
    "client_tool", "skill", "memory", "subagent",
})
STRUCTURAL = frozenset({"client_tool", "skill", "memory", "subagent"})
CAPABILITIES = frozenset({
    "bug_analysis", "bug_fix", "feature", "pr_review", "release_impact", "tech_debt",
})


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, value: Any) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True) + "\n")


def command_json(command: list[str], payload: dict[str, Any], cwd: Path, timeout: int) -> dict[str, Any]:
    if not command or not all(isinstance(part, str) and part for part in command):
        raise ValueError("command must be a nonempty array of strings")
    completed = subprocess.run(
        command, input=json.dumps(payload), text=True, capture_output=True,
        cwd=cwd, timeout=timeout, check=False,
    )
    if completed.returncode:
        raise RuntimeError(f"{command[0]} exited {completed.returncode}: {completed.stderr[-2000:]}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{command[0]} did not return one JSON object: {completed.stdout[-500:]}") from exc
    if not isinstance(result, dict):
        raise ValueError("adapter response must be a JSON object")
    return result


@dataclass(frozen=True)
class Config:
    root: Path
    baseline_harness: Path
    evolve_tasks: Path
    heldout_tasks: Path
    output_dir: Path
    proposer_command: list[str]
    runner_command: list[str]
    verifier_command: list[str]
    critic_command: list[str] | None
    protected_paths: tuple[str, ...]
    evidence_required_paths: tuple[str, ...]
    rounds: int
    trials_per_task: int
    calibration_repeats: int
    max_candidates: int
    budget_min: int
    budget_max: int
    stall_window: int
    exploration_slots: int
    prune_window: int
    beta0: float
    beta1: float
    within_score_weight: float
    within_cost_weight: float
    within_novelty_weight: float
    max_capability_drop: float
    max_domain_drop: float
    timeout_seconds: int

    @classmethod
    def load(cls, path: Path) -> "Config":
        raw = read_json(path)
        root = path.resolve().parent
        def location(key: str) -> Path:
            return (root / raw[key]).resolve()
        config = cls(
            root=root,
            baseline_harness=location("baseline_harness"),
            evolve_tasks=location("evolve_tasks"),
            heldout_tasks=location("heldout_tasks"),
            output_dir=location("output_dir"),
            proposer_command=raw["proposer_command"],
            runner_command=raw["runner_command"],
            verifier_command=raw["verifier_command"],
            critic_command=raw.get("critic_command"),
            protected_paths=tuple(raw.get("protected_paths", [])),
            evidence_required_paths=tuple(raw.get("evidence_required_paths", [])),
            rounds=int(raw.get("rounds", 5)),
            trials_per_task=int(raw.get("trials_per_task", 2)),
            calibration_repeats=int(raw.get("calibration_repeats", 3)),
            max_candidates=int(raw.get("max_candidates", 3)),
            budget_min=int(raw.get("budget_min", 1)),
            budget_max=int(raw.get("budget_max", 4)),
            stall_window=int(raw.get("stall_window", 3)),
            exploration_slots=int(raw.get("exploration_slots", 1)),
            prune_window=int(raw.get("prune_window", 4)),
            beta0=float(raw.get("beta0", 0.10)),
            beta1=float(raw.get("beta1", 44.5)),
            within_score_weight=float(raw.get("within_score_weight", 0.0)),
            within_cost_weight=float(raw.get("within_cost_weight", 1.0)),
            within_novelty_weight=float(raw.get("within_novelty_weight", 0.01)),
            max_capability_drop=float(raw.get("max_capability_drop", 0.05)),
            max_domain_drop=float(raw.get("max_domain_drop", 0.05)),
            timeout_seconds=int(raw.get("timeout_seconds", 300)),
        )
        if min(config.rounds, config.trials_per_task, config.calibration_repeats,
               config.max_candidates, config.budget_min, config.stall_window,
               config.prune_window, config.timeout_seconds) < 1:
            raise ValueError("rounds, counts, budgets, and timeout must be positive")
        if config.budget_max < config.budget_min or config.exploration_slots < 0:
            raise ValueError("invalid budget or exploration slots")
        if config.max_capability_drop < 0 or config.max_domain_drop < 0:
            raise ValueError("regression limits must be nonnegative")
        for entry in (*config.protected_paths, *config.evidence_required_paths):
            if not isinstance(entry, str) or not Path(entry).parts or Path(entry).is_absolute() or ".." in Path(entry).parts:
                raise ValueError(f"invalid protected path: {entry}")
        if config.evidence_required_paths and not config.critic_command:
            raise ValueError("evidence-required artifact edits need a critic_command")
        return config


def load_tasks(path: Path) -> list[dict[str, Any]]:
    tasks = read_json(path)
    if not isinstance(tasks, list) or not tasks:
        raise ValueError(f"{path} must contain a nonempty task list")
    ids: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict) or not isinstance(task.get("id"), str):
            raise ValueError("every task needs a string id")
        if task["id"] in ids or task.get("capability") not in CAPABILITIES:
            raise ValueError(f"duplicate id or unknown capability: {task['id']}")
        if not isinstance(task.get("input"), dict):
            raise ValueError(f"task {task['id']} needs a public input object")
        if "domain" in task and (not isinstance(task["domain"], str) or not task["domain"]):
            raise ValueError(f"task {task['id']} has an invalid domain")
        ids.add(task["id"])
    return tasks


def edit_budget(round_index: int, total_rounds: int, minimum: int, maximum: int) -> int:
    value = minimum + (maximum - minimum) * (1 + math.cos(math.pi * round_index / total_rounds)) / 2
    return math.ceil(value - 1e-12)


def seed_for(round_index: int, task_id: str, trial: int) -> int:
    digest = hashlib.sha256(f"{round_index}:{task_id}:{trial}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


def safe_harness_path(root: Path, relative: str) -> Path:
    requested = Path(relative)
    if requested.is_absolute() or ".." in requested.parts or not requested.parts:
        raise ValueError(f"invalid harness path: {relative}")
    target = root / requested
    if any(part.is_symlink() for part in [root, *list(target.parents)[:len(requested.parts)], target]):
        raise ValueError(f"symlinks are not allowed in harness edits: {relative}")
    return target


def copy_harness(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise ValueError(f"harness directory missing: {source}")
    for entry in source.rglob("*"):
        if entry.is_symlink():
            raise ValueError(f"harness contains a symlink: {entry}")
    shutil.copytree(source, destination)


def harness_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"harness contains a symlink: {path}")
        if path.is_file():
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def apply_candidate(incumbent: Path, destination: Path, edits: list[dict[str, Any]], budget: int,
                    protected_paths: tuple[str, ...] = (),
                    evidence_required_paths: tuple[str, ...] = ()) -> str:
    if not isinstance(edits, list) or not 1 <= len(edits) <= budget:
        raise ValueError(f"candidate must contain 1 to {budget} atomic edits")
    copy_harness(incumbent, destination)
    for edit in edits:
        if edit.get("component") not in COMPONENTS or not edit.get("hypothesis"):
            raise ValueError("each edit needs a known component and a hypothesis")
        target = safe_harness_path(destination, edit.get("path", ""))
        relative = target.relative_to(destination)
        if any(relative == Path(entry) or Path(entry) in relative.parents for entry in protected_paths):
            raise ValueError(f"candidate edits a protected source artifact: {relative}")
        if any(relative == Path(entry) or Path(entry) in relative.parents for entry in evidence_required_paths):
            sources = edit.get("sources")
            if not isinstance(sources, list) or not sources or not all(isinstance(s, str) and s.strip() for s in sources):
                raise ValueError(f"candidate needs source references for artifact edit: {relative}")
        operation = edit.get("operation")
        if operation == "delete":
            if not target.is_file():
                raise ValueError(f"cannot delete missing file: {target}")
            target.unlink()
        elif operation in {"add", "replace"}:
            content = edit.get("content")
            if not isinstance(content, str) or len(content.encode()) > 100_000:
                raise ValueError("edit content must be text under 100 KB")
            if operation == "add" and target.exists():
                raise ValueError(f"file already exists: {target}")
            if operation == "replace" and not target.is_file():
                raise ValueError(f"file does not exist: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        else:
            raise ValueError(f"unknown edit operation: {operation}")
    diff_lines: list[str] = []
    paths = {p.relative_to(incumbent) for p in incumbent.rglob("*") if p.is_file()}
    paths |= {p.relative_to(destination) for p in destination.rglob("*") if p.is_file()}
    for relative in sorted(paths):
        old = incumbent / relative
        new = destination / relative
        before = old.read_text(encoding="utf-8").splitlines(keepends=True) if old.exists() else []
        after = new.read_text(encoding="utf-8").splitlines(keepends=True) if new.exists() else []
        diff_lines.extend(difflib.unified_diff(before, after, fromfile=f"a/{relative}", tofile=f"b/{relative}"))
    diff = "".join(diff_lines)
    if not diff:
        raise ValueError("candidate makes no change")
    return diff


def screen_leakage(diff: str, tasks: list[dict[str, Any]]) -> str | None:
    lowered = diff.lower()
    for task in tasks:
        terms = [task["id"], *task.get("forbidden_terms", [])]
        for term in terms:
            if isinstance(term, str) and len(term) >= 5 and term.lower() in lowered:
                return f"candidate contains evolve-task identifier or forbidden term: {term}"
    return None


def feedback_from_trials(trials: list[dict[str, Any]]) -> dict[str, Any]:
    by_capability: dict[str, list[float]] = {}
    by_domain: dict[str, list[float]] = {}
    tags: dict[str, int] = {}
    for trial in trials:
        by_capability.setdefault(trial["capability"], []).append(trial["reward"])
        if trial.get("domain"):
            by_domain.setdefault(trial["domain"], []).append(trial["reward"])
        if trial["reward"] < 1:
            for tag in trial["failure_tags"]:
                tags[tag] = tags.get(tag, 0) + 1
    return {
        "capability_scores": {k: sum(v) / len(v) for k, v in sorted(by_capability.items())},
        "domain_scores": {k: sum(v) / len(v) for k, v in sorted(by_domain.items())},
        "failure_tags": dict(sorted(tags.items(), key=lambda item: (-item[1], item[0]))),
    }


def evaluate(config: Config, harness: Path, tasks: list[dict[str, Any]],
             round_index: int, label: str, run_dir: Path) -> dict[str, Any]:
    trials: list[dict[str, Any]] = []
    original_digest = harness_digest(harness)
    for task in tasks:
        for trial_index in range(config.trials_per_task):
            with tempfile.TemporaryDirectory(prefix="rrsi-task-") as workspace:
                runner_input = {
                    "task": {"id": task["id"], "capability": task["capability"], "input": task["input"]},
                    "harness_dir": str(harness), "seed": seed_for(round_index, task["id"], trial_index),
                    "workspace": workspace,
                }
                if "recorded_tools" in task:
                    runner_input["task"]["recorded_tools"] = task["recorded_tools"]
                response = command_json(config.runner_command, runner_input, config.root, config.timeout_seconds)
                if harness_digest(harness) != original_digest:
                    raise RuntimeError("runner modified the candidate harness during evaluation")
                tokens = response.get("policy_tokens")
                if not isinstance(tokens, (int, float)) or tokens < 0:
                    raise ValueError("runner must report nonnegative policy_tokens")
                verdict = command_json(config.verifier_command, {
                    "task": task, "agent_output": response, "workspace": workspace,
                }, config.root, config.timeout_seconds)
                reward = verdict.get("reward")
                if not isinstance(reward, (int, float)) or not 0 <= reward <= 1:
                    raise ValueError("verifier reward must be in [0, 1]")
                tags = verdict.get("failure_tags", [])
                if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
                    raise ValueError("failure_tags must be a string array")
                record = {"task_id": task["id"], "capability": task["capability"],
                          "trial": trial_index, "reward": float(reward),
                          "policy_tokens": float(tokens), "failure_tags": tags}
                if task.get("domain"):
                    record["domain"] = task["domain"]
                trials.append(record)
                append_jsonl(run_dir / "trials.jsonl", {"round": round_index, "label": label, **record})
    by_capability: dict[str, list[float]] = {}
    by_domain: dict[str, list[float]] = {}
    for trial in trials:
        by_capability.setdefault(trial["capability"], []).append(trial["reward"])
        if trial.get("domain"):
            by_domain.setdefault(trial["domain"], []).append(trial["reward"])
    category_scores = {key: sum(values) / len(values) for key, values in sorted(by_capability.items())}
    domain_scores = {key: sum(values) / len(values) for key, values in sorted(by_domain.items())}
    return {
        "score": sum(category_scores.values()) / len(category_scores),
        "policy_tokens": sum(trial["policy_tokens"] for trial in trials) / len(trials),
        "capability_scores": category_scores, "domain_scores": domain_scores, "trials": trials,
    }


def exploration_state(history: list[dict[str, Any]], scores: list[float],
                      round_index: int, delta: float, config: Config) -> dict[str, Any]:
    tried = {row["component"] for row in history}
    stalled = len(scores) > config.stall_window and scores[-1] - scores[-1-config.stall_window] <= delta
    prune = set()
    for component in tried:
        recent = [row["delta_score"] for row in history
                  if row["component"] == component and round_index - row["round"] <= config.prune_window]
        if not recent or max(recent) <= 0:
            prune.add(component)
    return {"stalled": stalled, "untried_components": sorted(COMPONENTS - tried),
            "prune_components": sorted(prune),
            "exploration_slots": config.exploration_slots if stalled else 0}


def select_candidate(candidate: dict[str, Any], incumbent: dict[str, Any],
                     best_score: float, delta: float, history: list[dict[str, Any]],
                     config: Config) -> tuple[bool, str, float, float]:
    result = candidate["evaluation"]
    score_change = result["score"] - incumbent["score"]
    cost_change = (result["policy_tokens"] - incumbent["policy_tokens"]) / max(incumbent["policy_tokens"], 1)
    if result["score"] < best_score - delta - 1e-12:
        return False, "below stability floor", score_change, cost_change
    if score_change > delta:
        if cost_change > config.beta0 + config.beta1 * score_change:
            return False, "cost exceeds gain allowance", score_change, cost_change
    else:
        accepted_components = {row["component"] for row in history if row["accepted"]}
        novelty = len(({edit["component"] for edit in candidate["edits"]} & STRUCTURAL) - accepted_components)
        shaped = (config.within_score_weight * score_change
                  - config.within_cost_weight * cost_change
                  + config.within_novelty_weight * novelty)
        if shaped <= 0:
            return False, "within noise band without cost or structural benefit", score_change, cost_change
    for capability, previous in incumbent["capability_scores"].items():
        current = result["capability_scores"].get(capability, 0)
        if previous - current > config.max_capability_drop + 1e-12:
            return False, f"regression in {capability}", score_change, cost_change
    for domain, previous in incumbent.get("domain_scores", {}).items():
        current = result.get("domain_scores", {}).get(domain, 0)
        if previous - current > config.max_domain_drop + 1e-12:
            return False, f"regression in domain {domain}", score_change, cost_change
    return True, "admissible", score_change, cost_change


def run(config: Config) -> Path:
    evolve = load_tasks(config.evolve_tasks)
    heldout = load_tasks(config.heldout_tasks)
    if {task["id"] for task in evolve} & {task["id"] for task in heldout}:
        raise ValueError("evolve and held-out task IDs must be disjoint")
    run_dir = config.output_dir / f"run-{uuid.uuid4().hex[:10]}"
    run_dir.mkdir(parents=True)
    incumbent_path = run_dir / "harnesses" / "H0"
    copy_harness(config.baseline_harness, incumbent_path)
    write_json(run_dir / "config.json", {key: str(value) if isinstance(value, Path) else value
                                           for key, value in asdict(config).items()})
    calibration = [evaluate(config, incumbent_path, evolve, -1-repeat, f"calibration-{repeat}", run_dir)
                   for repeat in range(config.calibration_repeats)]
    delta = max(item["score"] for item in calibration) - min(item["score"] for item in calibration)
    incumbent = calibration[0]
    best_score = max(item["score"] for item in calibration)
    write_json(run_dir / "calibration.json", {"delta": delta, "scores": [x["score"] for x in calibration]})
    history: list[dict[str, Any]] = []
    scores = [incumbent["score"]]
    for round_index in range(config.rounds):
        incumbent = evaluate(config, incumbent_path, evolve, round_index, "incumbent", run_dir)
        best_score = max(best_score, incumbent["score"])
        budget = edit_budget(round_index, config.rounds, config.budget_min, config.budget_max)
        state = exploration_state(history, scores, round_index, delta, config)
        proposal_request = {
            "round": round_index, "total_rounds": config.rounds, "edit_budget": budget,
            "max_candidates": config.max_candidates, "incumbent_harness_dir": str(incumbent_path),
            "feedback": feedback_from_trials(incumbent["trials"]), "history": history,
            "protected_paths": config.protected_paths,
            "evidence_required_paths": config.evidence_required_paths,
            **state,
        }
        write_json(run_dir / f"round-{round_index}-request.json", proposal_request)
        proposals = command_json(config.proposer_command, proposal_request, config.root, config.timeout_seconds)
        candidates = proposals.get("candidates")
        if not isinstance(candidates, list) or len(candidates) > config.max_candidates:
            raise ValueError("proposer must return candidates array within max_candidates")
        if state["stalled"] and state["untried_components"]:
            exploratory = sum(bool({edit.get("component") for edit in item.get("edits", [])}
                                   & set(state["untried_components"])) for item in candidates)
            if exploratory < min(config.exploration_slots, len(candidates)):
                raise ValueError("stalled proposal did not reserve exploratory candidates")
        measured: list[dict[str, Any]] = []
        for index, proposal in enumerate(candidates):
            candidate_id = f"r{round_index}-c{index}"
            edits = proposal.get("edits", [])
            path = run_dir / "candidates" / candidate_id
            try:
                diff = apply_candidate(incumbent_path, path, edits, budget,
                                       config.protected_paths, config.evidence_required_paths)
                reason = screen_leakage(diff, evolve)
                if reason is None and config.critic_command:
                    critic = command_json(config.critic_command, {
                        "diff": diff, "edits": edits,
                        "evolve_task_ids": [task["id"] for task in evolve],
                        "forbidden_terms": sorted({term for task in evolve for term in task.get("forbidden_terms", [])}),
                        "ground_truth_paths": config.protected_paths,
                    }, config.root, config.timeout_seconds)
                    if critic.get("approved") is not True:
                        reason = str(critic.get("reason", "critic rejected candidate"))
                if reason:
                    append_jsonl(run_dir / "candidates.jsonl", {"round": round_index, "id": candidate_id,
                                                                 "status": "screened", "reason": reason})
                    continue
                evaluation = evaluate(config, path, evolve, round_index, candidate_id, run_dir)
                candidate = {"id": candidate_id, "edits": edits, "diff": diff,
                             "harness_dir": str(path), "evaluation": evaluation}
                admissible, reason, gain, cost = select_candidate(candidate, incumbent, best_score,
                                                                    delta, history, config)
                candidate.update({"admissible": admissible, "reason": reason,
                                  "delta_score": gain, "delta_cost": cost})
                measured.append(candidate)
                append_jsonl(run_dir / "candidates.jsonl", {
                    "round": round_index, "id": candidate_id, "status": "measured",
                    "score": evaluation["score"], "policy_tokens": evaluation["policy_tokens"],
                    "admissible": admissible, "reason": reason, "diff": diff,
                })
            except ValueError as exc:
                append_jsonl(run_dir / "candidates.jsonl", {"round": round_index, "id": candidate_id,
                                                             "status": "invalid", "reason": str(exc)})
                if path.exists():
                    shutil.rmtree(path)
        admissible = [item for item in measured if item["admissible"]]
        winner = max(admissible, key=lambda item: (item["evaluation"]["score"],
                                                    -item["evaluation"]["policy_tokens"], item["id"])) if admissible else None
        for item in measured:
            for edit in item["edits"]:
                row = {"round": round_index, "candidate_id": item["id"],
                       "component": edit["component"], "hypothesis": edit["hypothesis"],
                       "sources": edit.get("sources", []),
                       "diff": item["diff"], "delta_score": item["delta_score"],
                       "delta_cost": item["delta_cost"], "accepted": item is winner}
                history.append(row)
                append_jsonl(run_dir / "history.jsonl", row)
        if winner:
            incumbent_path = Path(winner["harness_dir"])
            incumbent = winner["evaluation"]
            best_score = max(best_score, incumbent["score"])
        scores.append(incumbent["score"])
        append_jsonl(run_dir / "rounds.jsonl", {"round": round_index, "winner": winner["id"] if winner else None,
                                                     "score": incumbent["score"], "best_score": best_score,
                                                     "policy_tokens": incumbent["policy_tokens"]})
    # Held-out tasks are touched exactly once, after proposal and selection are complete.
    baseline_heldout = evaluate(config, run_dir / "harnesses" / "H0", heldout, 10_000, "heldout-baseline", run_dir)
    final_heldout = evaluate(config, incumbent_path, heldout, 10_000, "heldout-final", run_dir)
    summary = {
        "incumbent_harness_dir": str(incumbent_path), "noise_band": delta,
        "evolve_score": incumbent["score"], "evolve_policy_tokens": incumbent["policy_tokens"],
        "heldout_baseline": {key: value for key, value in baseline_heldout.items() if key != "trials"},
        "heldout_final": {key: value for key, value in final_heldout.items() if key != "trials"},
        "rounds": config.rounds,
    }
    write_json(run_dir / "summary.json", summary)
    return run_dir
