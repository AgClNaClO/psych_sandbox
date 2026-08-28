# Domain and module map

Read this file when changing simulation flow, information permissions, therapy adapters, evaluation or persistence.

## Stable terms

- **Case**: one source-grounded runnable record from `data/<therapy>`.
- **Session**: one bounded consultation containing several counselor/client turns and consolidation.
- **Plan**: the current therapy stage, objectives, allowed meta skills and carry-over strategy.
- **Memory**: spoken evidence, evolving profile, summaries, unresolved items and skill history. A hidden fact is not memory until client wording supplies verifiable evidence.
- **Counselor review**: session-boundary API assessment of goal evidence and, when needed, a revised strategy.
- **Rule evaluation**: deterministic per-session audit; it does not choose the next plan.
- **Holistic supervision**: API PsychEval scoring once after all sessions; it does not choose the next plan.
- **Session candidate**: one complete simulated session from a common pre-session context; unselected candidates never become counselor memory or committed sessions.
- **RFT selection reward**: a separate, evidence-bound research score for comparing eligible session candidates. It selects a session, not the next plan, and is not a clinical outcome measure.

## Ownership

| Path | Owns |
|---|---|
| `domain/` | Pydantic contracts for cases, plans, turns, memory, evaluation and results |
| `datasets/` | five-therapy conversion and runnable-case indexing |
| `therapies/` | therapy identifiers, stages, objectives and metric mapping |
| `agents/` | client planning/generation and counselor plan→act→observe→respond/review |
| `skills/` | skill registry, exact-ID catalog observation and conditional vector narrowing |
| `runtime/` | orchestration, isolated session candidates, disclosure, safety, state, memory and storage |
| `runtime/run_management.py` | read-only deletion previews, confirmed run cleanup and retry journals |
| `evaluation/` | rule, client-simulation, longitudinal, independent session RFT and holistic evaluation |
| `visualization/` | read-only HTML/SVG reporting from normalized results |

## Cross-module invariants

1. Counselor-visible context is assembled from disclosed evidence and allowed memory only.
2. Client language generation receives planner-authorized new facts plus already spoken evidence only.
3. Final strategy choice stays with the model; code validates IDs/public evidence, narrows large candidate sets by vector similarity and enforces the single-correction budget. See `../SKILL_SELECTION.md` for this boundary.
4. The next plan combines counselor review with longitudinal stage action, not evaluator scores.
5. SQLite, JSONL and HTML represent the same normalized `RunResult` contracts.
6. RFT uses the previous committed winner as its sole baseline. Only the selected session enters consolidation; failed, duplicate and rejected branches stay in separate audit storage. See `../SESSION_RFT.md`.
7. Confirmed run deletion removes only that run's records/files. Shared cases/skills survive; deletion journals block resume and report writers until cleanup is complete. Directory absence alone is not deletion consent.
