# Repository guidance

## Verification

Use Python 3.11+ with `.[dev]`. Run `pytest -q` before completing code or resource changes; completion means all tests under `tests/` pass. Keep credentials, virtual environments, generated runs, downloaded data, processed caches and bytecode outside Git according to `.gitignore`.

Keep generated artifacts under `runs/tests` or `runs/runtime`, with one directory per invocation. Use `tmp_path` for test output. Read `docs/RUN_ARTIFACTS.md` when adding output paths, temporary files, CLI commands or artifact migrations; preserve retained runs and the shared runtime database. Use `runs delete --run <id>` for a read-only preview and `--yes` for explicit deletion. Read `docs/RUN_ARTIFACTS.md` before changing cleanup: honor run locks and deletion journals, retain shared cases/skills, and never infer deletion authority merely from a missing directory.

## Runtime invariants

- Production simulation is API-only; deterministic gateways are test doubles under `tests/`.
- Counselor context contains disclosed evidence and allowed memory, not the full private client profile.
- Skill selection preserves the asset tree: therapy/stage filtering, evidence-backed model IDs, exact catalog expansion, then vector narrowing only above the configured threshold. Read `docs/SKILL_SELECTION.md` before changing skill metadata, filtering or query retries; at most one correction query may exclude the previous groups.
- Counselor review plus longitudinal progress builds the next session plan. Per-session rule evaluation is audit evidence, and `PsychEvalSupervisor` scores once after the complete trajectory; neither score drives planning.
- Session RFT is optional: isolate candidate state, apply safety/validity gates, rank complete sessions, and commit only the winner. Read `docs/SESSION_RFT.md` before changing rollout, reward, selection or recovery behavior.
- BT, CBT, HET, PDT and PMT keep separate cases, skill trees, therapy profiles and specific metrics.

Read `docs/agents/domain.md` before changing simulation boundaries or domain terms. Read `docs/agents/issue-tracker.md` before GitHub issue operations; its label pointer leads to the current remote-label compatibility mapping.
