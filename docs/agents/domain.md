# Domain and module map

Read this file when changing simulation flow, information permissions, therapy adapters, evaluation or
persistence.

## Stable terms

- **Case**: one source-grounded runnable record from `data/<therapy>`.
- **Session**: one bounded consultation containing several counselor/client turns and consolidation.
- **Plan**: the current therapy stage, objectives, allowed meta skills and carry-over strategy.
- **Memory**: spoken evidence, evolving profile, summaries, unresolved items and skill history. A hidden fact is
  not memory until client wording supplies verifiable evidence.
- **Counselor review**: session-boundary API assessment of goal evidence and, when needed, a revised strategy.
- **Rule evaluation**: deterministic per-session audit; it does not choose the next plan.
- **Holistic supervision**: API PsychEval scoring once after all sessions; it does not choose the next plan.

## Ownership

| Path | Owns |
|---|---|
| `domain/` | Pydantic contracts for cases, plans, turns, memory, evaluation and results |
| `datasets/` | five-therapy conversion and runnable-case indexing |
| `therapies/` | therapy identifiers, stages, objectives and metric mapping |
| `agents/` | client planning/generation and counselor plan→act→observe→respond/review |
| `skills/` | skill registry and exact-ID catalog observation |
| `runtime/` | orchestration, disclosure, safety, state, memory and storage |
| `evaluation/` | rule, client-simulation, longitudinal and holistic evaluation |
| `visualization/` | read-only HTML/SVG reporting from normalized results |

## Cross-module invariants

1. Counselor-visible context is assembled from disclosed evidence and allowed memory only.
2. Client language generation receives planner-authorized new facts plus already spoken evidence only.
3. Semantic strategy choice stays with the model; code validates IDs and enforces hard boundaries.
4. The next plan combines counselor review with longitudinal stage action, not evaluator scores.
5. SQLite, JSONL and HTML represent the same normalized `RunResult` contracts.
