# Repository guidance

## Verification

Use Python 3.11+ with `.[dev]`. Run `pytest -q` before completing code or resource changes; completion means all
tests under `tests/` pass. Keep credentials, virtual environments, generated runs, downloaded data, processed
caches and bytecode outside Git according to `.gitignore`.

## Runtime invariants

- Production simulation is API-only; deterministic gateways are test doubles under `tests/`.
- Counselor context contains disclosed evidence and allowed memory, not the full private client profile.
- Skill selection is therapy/stage hard filtering followed by model-selected IDs and exact catalog observation;
  preserve this no-ranking ReAct seam.
- Counselor review plus longitudinal progress builds the next session plan. Per-session rule evaluation is audit
  evidence, and `PsychEvalSupervisor` scores once after the complete trajectory; neither score drives planning.
- BT, CBT, HET, PDT and PMT keep separate cases, skill trees, therapy profiles and specific metrics.

Read `docs/agents/domain.md` before changing simulation boundaries or domain terms. Read
`docs/agents/issue-tracker.md` before GitHub issue operations; its label pointer leads to the current remote-label
compatibility mapping.
