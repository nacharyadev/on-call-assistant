# Bootstrap contract

## Modes

| Existing harness | Domain selection | Required behavior |
| --- | --- | --- |
| No | All | Discover every candidate repository, establish domains, and generate a complete initial harness. |
| No | Selected | Inspect explicit repositories and related dependencies for the named domain; report unresolved domain boundaries. |
| Yes | All | Compare recorded and current commits, refresh affected mappings, then validate the complete harness. |
| Yes | Selected | Refresh the selected domains and any cross-domain contracts affected by repository deltas; preserve unrelated mappings. |

`fresh` never means deleting an existing destination. If harness files already exist, stop and use `update` or a new destination.

## Source precedence

Prefer evidence in this order when sources disagree:

1. Accepted architecture decisions, versioned API/event schemas, and executable contracts.
2. Current implementation, dependency declarations, routes, handlers, and tests.
3. CODEOWNERS and repository documentation.
4. Naming and directory structure, which remain provisional until corroborated.

Record disagreements instead of silently choosing a convenient answer. A merged implementation can show current behavior while an accepted decision shows intended behavior; preserve that distinction in context documents.

## Repository evidence to inspect

- Git remote and current commit.
- CODEOWNERS or equivalent ownership metadata.
- Package and deployment manifests.
- Application entrypoints and service configuration.
- Frontend routes, screens, network clients, and end-to-end tests.
- HTTP/RPC/GraphQL specifications, controllers, handlers, and clients.
- Event schemas, producers, consumers, topics, and idempotency identifiers.
- Feature flag definitions and references.
- Unit, integration, contract, and browser test paths.
- ADRs, PRDs, runbooks, and domain glossaries.

Avoid scanning vendored dependencies, generated output, build artifacts, virtual environments, or secret files.

## `discovery-report.json`

Keep this versioned at the harness root. It should contain:

```json
{
  "schema_version": 1,
  "generated_at": "2026-09-27T12:00:00Z",
  "mode": "update",
  "scope": {"domains": ["inventory"]},
  "repositories": [
    {
      "name": "acme/inventory-api",
      "previous_commit": "abc123",
      "commit": "def456",
      "dirty": false,
      "inspected_paths": ["src/api/availability.py", "tests/test_availability.py"]
    }
  ],
  "changes": [
    {
      "artifact": "feature-map.json",
      "target": "inventory availability",
      "change": "updated API handler and regression test paths",
      "evidence": [
        {"repository": "acme/inventory-api", "commit": "def456", "path": "src/api/availability.py"}
      ],
      "confidence": "verified"
    }
  ],
  "unresolved": []
}
```

Do not put absolute local paths in the versioned report. The local `.oca/workspace-scan.json` may contain paths and is ignored.

## Fresh harness minimum

A usable fresh harness contains:

```text
harness/
├── team/team-artifact.json
├── feature-map.json
├── discovery-report.json
├── prompts/classifier.txt
├── prompts/planner.txt
├── prompts/response.txt
├── prds/
├── decisions/
├── runbooks/
└── trajectory_cases.json
```

Empty documentation directories are optional until a verified source requires a document. Copy generic prompts from the OCA empty harness template; keep domain facts in the team artifact, feature map, vocabulary, and context documents.
