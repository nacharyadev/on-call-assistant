# Failure-driven prompt tuning example

## Measured failure

A trajectory case requests investigation of a material issue that affects warehouse, inventory, and manufacturing. The planner selects only `inventory` even though the team artifact and feature map identify all three owning domains. Repository and tool selection are otherwise correct.

Failure tag:

```text
missing_domain:warehouse
missing_domain:manufacturing
```

## Poor correction

```text
When the request mentions work order WO-4822 or lot LOT-77, always select inventory,
warehouse, and manufacturing.
```

This memorizes case identifiers and will not transfer to another customer or product flow.

## Better correction

Add one generic instruction to the planner prompt near its feature-selection guidance:

```text
When a selected feature spans multiple owning domains, include every domain needed to
load its contracts and vocabulary. Keep focus_repositories limited to repositories that
need tool work; selecting a domain for context does not require scheduling a worker in
every repository.
```

Why this is better:

- It uses the supplied feature map rather than benchmark wording.
- It distinguishes context breadth from worker fanout.
- It applies to other cross-domain features.
- It does not weaken repository or tool constraints.

## Verification

Rerun the failing case and the full visible evolve/regression suite. Accept the prompt change only when it fixes the missing domains without causing extra focus repositories, tools, or token cost beyond the configured guard. Keep held-out cases untouched until the final transfer evaluation.

## Response-prompt example

Measured failure: a release-impact answer states that a regression is confirmed from changed-file matches.

Small generic correction:

```text
Treat changed-file and feature-map matches as impact candidates. Call impact confirmed
only when runtime evidence or an executable verifier establishes the behavior.
```

Do not add repository names, release tags, expected owners, or test paths to the prompt. Those facts belong in the feature map, task evidence, and verifier.
