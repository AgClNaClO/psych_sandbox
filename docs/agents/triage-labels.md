# Triage label compatibility

GitHub currently exposes the standard labels `bug`, `documentation`, `duplicate`, `enhancement`,
`good first issue`, `help wanted`, `invalid`, `question` and `wontfix`. Dedicated Matt Pocock workflow-state
labels are not configured, so agent workflows use this compatibility mapping:

| Workflow role | Repository label | Use |
|---|---|---|
| `needs-triage` | `question` | Request still needs classification or clarification |
| `needs-info` | `question` | Waiting on reporter information; state the missing information in a comment |
| `ready-for-agent` | `help wanted` | Request is specified well enough for implementation |
| `ready-for-human` | `enhancement` | Valid request needing maintainer or domain-expert judgment |
| `wontfix` | `wontfix` | Repository will not action the request |

Because two workflow roles share `question`, the latest issue comment is the source of truth for the precise
state. If dedicated state labels are added remotely, update this mapping before using them in agent workflows.
