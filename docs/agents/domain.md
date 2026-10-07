# Domain and module map

Read this file when changing simulation flow, information permissions, therapy adapters, evaluation or persistence.

## Stable terms

- **Case**: one source-grounded runnable record from `data/<therapy>`.
- **Session**: one bounded consultation containing several counselor/client turns and consolidation.
- **Plan**: the current therapy stage, objectives, allowed meta skills and carry-over strategy.
- **Memory**: the four-field `SessionMemory` the counselor keeps across sessions — `known_background` (disclosed evidence with fact-level provenance), `session_recaps` (one recap per finished session), `last_homework` (open assignments with status), and `checklist` (per-session archived items plus the still-open follow-up items). A private evidence atom is not counselor memory until client wording supplies verifiable evidence; `case_id` and `migration_warnings` are management fields.
- **Memory read view**: the bounded, layered projection of that memory that the counselor actually reads each turn (`runtime/memory_view.py`, `SandboxConfig.memory_view`). It drops management fields and audit-only logs and, in `recap_window` mode, keeps the current focus plus a recent window inside an explicit character budget.
- **Session checklist**: model-selected working memory for completed items, important information, methods, results and pending items. It starts empty for each session and is archived into `checklist.per_session` at session close (and reconciled with the full dialogue by E.9).
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
| `runtime/progress.py` | live CLI progress labels and the rendering contract for candidate and scoring bars |
| `evaluation/` | rule, longitudinal, independent session RFT and holistic evaluation |
| `visualization/` | read-only HTML/SVG reporting from normalized results |

## Cross-module invariants

1. Counselor-visible context is assembled from disclosed evidence and allowed memory only.
2. Client language generation receives planner-authorized new facts plus already spoken evidence only.
3. Final strategy choice stays with the model; code validates IDs/public evidence, narrows large candidate sets by vector similarity and enforces the single-correction budget. See `../SKILL_SELECTION.md` for this boundary.
4. The next plan combines counselor review with longitudinal stage action, not evaluator scores.
5. SQLite, JSONL and HTML represent the same normalized `RunResult` contracts.
6. RFT uses the previous committed winner as its sole baseline. Only the selected session enters consolidation; failed, duplicate and rejected branches stay in separate audit storage. See `../SESSION_RFT.md`.
7. Confirmed run deletion removes only that run's records/files. Shared cases/skills survive; deletion journals block resume and report writers until cleanup is complete. Directory absence alone is not deletion consent.
8. `ClientProfile.schema_version="4"` versions the private client case contract. `trace_schema_version=5` independently versions persisted trajectory/memory structure (bumped when `SessionMemory` moved to its four-field layout); matching numbers do not make them the same schema.
9. The session checklist never carries over as active state. E.9 reconciles it with the full dialogue, then it is archived into `checklist.per_session` as counselor-visible longitudinal memory.
10. Memory retirement is evidence-bound: an item only leaves `last_homework`/`checklist.open_items` through an id-addressed `item_updates` entry whose `done` evidence occurs in that session's dialogue (or through a normalized/fuzzy match with the session's `completed_items`).
11. Optional probability-weighted (logprob) scoring changes only how a PsychEval scale total is aggregated. An endpoint without a logprob payload, or a judgement whose numeric mass falls below the floor, fails loudly and is never replaced by an item average or zero. See `../../notes/logprob_scoring_borrowing.md`.
12. Client idling detection is counselor-side engineering evidence read only from the visible dialogue and previous `ClientTurnSignal` behaviours. It needs at least three observed client turns and two of three cues (repeated content, consecutive `simple_response`, minimal-answer density); the thresholds are hypotheses, not clinical cut-offs, and a detected idle turn replaces one skill-based counselor turn.
13. Attachment conditioning is prompt-level guidance for the planned `trust_change` only, and only when the profile carries a conditioned pattern whose `source_fact_ids` resolve to existing evidence nodes at sufficient confidence. It is never case evidence, never a disclosure permission and never counselor memory; without that evidence it stays absent rather than inferred from the case.
