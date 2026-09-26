# Parallel-session migration

The project directory is now `~/dev/on-call-assistant`. `~/dev/rrsi-oncall` is a symlink to it while the other session finishes migrating. New edits should target the new directory and the `on_call_assistant` package. The `rrsi_oncall` package contains compatibility imports only.

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

The new console scripts are `on-call-assistant`, `on-call-trajectory`, and `on-call-evolve`. The previous `rrsi-*` script names still point to the new implementations. After all sessions and deployments use the new imports and paths, the compatibility wrappers and symlinks can be removed in a separate change.
