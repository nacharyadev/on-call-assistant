# Package migration

Use the `on_call_assistant` package for new imports. The `rrsi_oncall` package contains compatibility imports for older integrations. The repository can be checked out at any filesystem path.

| Previous location | New location |
| --- | --- |
| `rrsi_oncall.oca.graph`, `.planning`, `.state`, `.impact`, `.safety` | `on_call_assistant.agent.*` |
| `rrsi_oncall.oca.harness` | `on_call_assistant.knowledge.loader` |
| `rrsi_oncall.oca.model`, `.tools` | `on_call_assistant.integrations.*` |
| `rrsi_oncall.oca.service` | `on_call_assistant.api.service` |
| `rrsi_oncall.oca.trajectory` | `on_call_assistant.evaluation.trajectory` |
| `rrsi_oncall.oca.trajectory_cli` | `on_call_assistant.evaluation.cli` |
| `rrsi_oncall.core`, `.cli` | `on_call_assistant.evolution.core`, `.cli` |
| `examples/oca_harness` | `examples/agent_harness` |
| `examples/oca_trajectory_cases.json` | `examples/trajectory_cases.json` |

The new console scripts are `on-call-assistant`, `on-call-trajectory`, and `on-call-evolve`. The previous `rrsi-*` script names still point to the new implementations. Remove the compatibility wrappers only after older integrations have migrated.
