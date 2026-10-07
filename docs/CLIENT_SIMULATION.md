# Client simulation audit and implementation

Reference checkout re-verified on 2026-10-07 at
`C:\Users\Rain\Desktop\PatientHub-master`; the `D:/PatientHub-master` path used
by the first audit no longer exists. That directory still has **no** `.git`
metadata, so this comparison identifies files and their content fingerprints
rather than claiming an upstream revision or a paper reproduction. Its
`README.md` identifies *PatientHub: A Unified Framework for Patient Simulation*
(EMNLP 2026 Demo) and *PatientAct: Theory-Grounded Mental Health Client
Simulation* (EMNLP 2026 Findings).

Audited files, recorded as SHA-256 prefixes (12 hex characters) with byte size:

| Reference file | SHA-256 prefix (bytes) |
| --- | --- |
| `patienthub/clients/patientAct.py` | `c63902e99430` (13650) |
| `patienthub/schemas/patientAct.py` | `3c055fb277bd` (15660) |
| `patienthub/generators/patientAct.py` | `a0628351877b` (19087) |
| `data/prompts/client/patientAct.yaml` | `2f7ea07f6184` (12150) |
| `data/prompts/generator/patientAct.yaml` | `0b6aa9b57a7d` (10049) |
| `docs/docs/components/clients/patientact.md` | `a0d7ac27eec1` (10839) |
| `patienthub/evaluators/conv.py` | `dcb064aaaf79` (2031) |
| `data/prompts/evaluator/client_conv.yaml` | `600613ddba82` (2909) |
| `data/characters/patientAct.json` | `2eb0f5c428c5` (1178154) |

The reference checkout is **not** part of this repository, so the `patienthub/...`
files named below cannot be re-verified from this checkout and only the
sandbox-side behaviour is reproducible here.

## Baseline audit

`ClientProfile` schema v4 contains PsychEval evidence nodes, five-therapy native
`theory` projections, a cross-therapy 5Ps projection, atomic `disclosure_items`,
source-backed `interaction_prior` and `expression_style`, and initial state.
Legacy `personality` and `relational` fields are excluded from serialization.
Their existence did not mean they reached the planner.

`ClientState` contains valence, arousal, distress, trust, resistance, hope,
fatigue and rupture state. These are simulation variables, not clinical scales.
`ClientTurnSignal` describes reaction/intensity, behavior, conditional resistance
pattern, retrieved/blocked IDs and a trust direction. Its validator removes a
resistance pattern unless behavior is resistance.

`DisclosureItem` already expressed trust tier, activation tags/examples,
dependencies, session scope and a discomfort flag. The Boolean discomfort flag
was not a graded emotional cost. `BlockedMemorySignal` already exposed metadata
without fact content. Tags are matched locally by `TagActivationMatcher`; generic
tags require stronger evidence, and tied candidates request clarification.

The existing call path was:

```text
runtime._run_session
  -> ClientSimulator.respond
  -> DisclosureGate.evaluate
  -> ClientPolicy.plan_turn (ClientAgent in compact mode)
  -> ClientAgent.generate_utterance
  -> leakage inspect / retry / substantiate spoken fragments
  -> DisclosureGate.unlock
  -> StateUpdater.update
  -> runtime merges spoken facts and advances state
```

The generator already received selected retrieved atoms, spoken memories,
expression guidance and state, not the full private profile. However, the full
planner signal included its rationale; that was a potential side channel for
private details despite prompt instructions. Generation retries stayed inside
the generator, so state updates occurred once after acceptance.

The runtime carries final state into the next turn. Session boundaries retain
emotion, partially retain trust, recover fatigue and reset resistance to the
case baseline. They previously also reset rupture, losing unresolved relational
damage. Spoken facts carry through `SessionMemory.known_background.facts`.
E.7/E.8/E.9 consolidation runs at session close. Existing RFT workers deep-copy
case, plan, memory and state, and only the winner proceeds to consolidation.
No baseline evidence indicated duplicate state updates or losing-branch commits.

Necessary differences from PatientHub are PsychEval-only case facts, independent
therapy formulations, 0-1 trust, session scope, dependency chains, ambiguity
handling, spoken-evidence checks and a separate counselor memory view. These
features must not be replaced by the reference's simpler contracts.

## PatientHub source comparison

Read reference files: `docs/docs/components/clients/patientact.md`,
`patienthub/clients/patientAct.py`, `patienthub/schemas/patientAct.py`,
`patienthub/generators/patientAct.py`, `patienthub/resources/big_five.py`,
and `patienthub/resources/emotions.py`.

| Mechanism | PatientHub implementation | Sandbox implementation / decision |
| --- | --- | --- |
| Facts | Generated problem/psychological formulation, demographic scaffold and validation loops | PsychEval evidence is the sole case-fact source; no generated cases copied |
| Memory | Extracted profile fields with `field_path`, content, disclosure level, tags and discomfort | Evidence-backed atomic items plus spoken fragments, scope and dependencies |
| Trust | Starts at 2.5, clamps to 1-4, changes by 0.25 or 0.5 | Existing 0-1 tiers and smaller deltas retained |
| Activation | Structured model topic extraction followed by tag intersection | Auditable local tag matching retained; no additional topic-model call |
| Blocked | `retrieve_context` appends blocked content strings | Metadata only; blocked content and planner rationale never enter generator |
| Pipeline | Separate reaction, behavior, conditional resistance, response and trust calls | Compact remains one planning call; faithful trust decision moved after accepted response |
| Trust input | `conv_history` is built before response and reused by the subsequent trust call | Faithful critic explicitly receives accepted current response |
| Disclosure evidence | Reference retrieval/response path has no equivalent atom substantiation ledger | Existing evidence checks retained; unlock API now also requires authorization and evidence |
| Personality | Big Five guidance resource exists but PatientAct does not call it | New explicitly synthetic private config, neutral/inert defaults, bounded modifiers |
| Emotions | GoEmotions resource exists but PatientAct uses its own seven reactions | Existing seven reactions and continuous state retained; no unused discrete tags |
| No-memory ablation | Full private profile in system prompt | Disable new retrieval while retaining previously spoken evidence; deliberately not an exact replica |

## Implemented changes and verification

| Files | Change / purpose | Verification |
| --- | --- | --- |
| `src/psychsandbox/domain/models.py`, `domain/__init__.py` | Optional private `ClientSimulationConfig` (traits, origin, source IDs, uncertainty, version); optional emotional cost; ablation configuration | Private config round-trip, inert uncertain defaults, bounded influence and old-profile loading |
| `src/psychsandbox/agents/client.py` | Send derived expression modifiers, omit rationale/trust direction from generator, expose pipeline mode | Inspect actual generation payload for blocked content and private rationale |
| `src/psychsandbox/client_simulation/policies.py` | Faithful reaction/behavior/conditional resistance before response; trust critic after final accepted response | Ordering, conditional resistance and exact model-call accounting |
| `src/psychsandbox/client_simulation/simulator.py` | Optional post-response policy finalization; ablations; carry unresolved rupture | Retry updates trust/state once, cross-session spoken evidence, rupture carry-over |
| `src/psychsandbox/runtime/disclosure.py` | Optional trust-only bypass; unlock requires retrieved ID and nonempty spoken evidence | Sensitive content blocked normally; scope/dependencies remain enforced; no evidence-free backfill |
| `src/psychsandbox/runtime/state.py` | Separate appraisal features for emotion instead of using goal progress for every dimension | Trust and distress rise together; avoidance does not raise hope; goal score alone changes no emotion; gradual repair |
| `src/psychsandbox/config.py`, `configs/runtime.yaml` | Read/default three ablation flags | YAML false values survive loading |
| `src/psychsandbox/runtime/orchestrator.py` | Apply flags to ordinary and RFT turns; record effective policy and flags in trajectory config | Existing end-to-end and candidate-isolation suite |
| `prompts/simclient/*.jinja2`, `client_simulation/prompts.py` | Explicit synthetic guidance and free expression in pipeline ablation; prompt version v6 | Prompt contracts and generation payload checks |
| `tests/test_client_mechanism_boundaries.py`, `test_client_policies.py`, `test_components.py` | Add boundary tests; update intentional faithful order and evidence-required unlock contracts | Full suite, without removing prior boundary assertions |
| `docs/CLIENT_SIMULATION.md` | Audit, reference differences, experiment semantics and limitations | Compared to source and final diff |

No counselor, supervisor, skill-tree, model-selection, RFT ranking or memory
consolidation implementation is changed. No new package dependency is added.
Appraisal is recorded in existing private turn audit, not counselor memory.
New profile fields are optional defaults, keeping old v4 profiles loadable;
the existing profile/trace versions remain 4/5. Prompt behavior is versioned v7.

## Research configuration

The YAML `client` block supports `policy: compact_patientact` or
`faithful_patientact`, plus `use_memory`, `use_pipeline`, `use_trust_gating` and
`topic_matcher` (`tags` by default, `semantic` for the local n-gram ablation).
All three switches default to true, and `topic_matcher` keeps the auditable
`tags` default. Direct Python configuration uses the
corresponding `SandboxConfig.client_use_*` fields.

- `use_memory=false`: no dynamic retrieval or newly authorized facts; previously
  spoken evidence remains available across sessions. This protects the case
  firewall, so it is not PatientHub's full-private-profile static baseline.
- `use_pipeline=false`: no reaction/behavior planning call; language generation
  chooses expression freely while retaining disclosure/leakage checks. The
  compatibility simple policy keeps trust direction unchanged. This also removes
  model reaction/trust adaptation, so it is a broader ablation than just behavior.
- `use_trust_gating=false`: bypass trust thresholds only. Topic matching, scope,
  dependencies, ambiguity and spoken-evidence checks remain active.

Legacy `patientact.enabled=false` continues selecting the simple policy.
Compact makes one planning call and applies its provisional trust direction only
after generation. Faithful uses two planning calls, a conditional resistance
call, one generation call (plus retries), and one post-response trust call.
`client.topic_matcher` selects `tags` (default) or `semantic`; the choice is
recorded in the trajectory snapshot.

`profile.simulation_config` is private, persisted simulation configuration.
Traits are never automatically inferred from PsychEval. Uncertainty 1.0 makes
all modifiers zero; lower uncertainty allows at most 0.1 expression preference
or 0.05 threat/recovery adjustment. Expression is prompt-level guidance;
threat/recovery actually scale state deltas. Legacy excluded personality is not
silently promoted. No personality-based disclosure-threshold offset is added.

## Second borrowing round (PatientAct checklist)

Three checklist items were implemented in this round. All of them are additive:
the default runtime path keeps the auditable tag matcher, and the client prompt
version moves to `psycheval_patientact_v7`.

### Client content-exhaustion (idling) detection

`DialogueLoopGuard.inspect_client_idling` reads only the counselor-visible
dialogue plus the previous `ClientTurnSignal` behaviours. It counts three cues
over the last `IDLE_WINDOW = 4` client turns: repeated client content,
consecutive `simple_response` behaviours (`>= IDLE_MIN_SIMPLE_RESPONSES = 2`) and
minimal-answer marker density (`>= IDLE_MIN_WITHDRAWALS = 2`). At least
`IDLE_MIN_SIGNALS = 2` cues must agree after at least `IDLE_MIN_CLIENT_TURNS = 3`
observed client turns, so one short answer never triggers a repair. A detected
signal makes `CounselorAgent` answer with a direction-change repair
(`IDLE_REPAIR`, then `IDLE_HANDOVER` when a repair was already sent) instead of
repeating the probe; the detected reasons and the observed turn count are written
into the counselor decision for audit. The client's own planning, state and
disclosure permission are untouched. The thresholds are engineering hypotheses
and are configurable through the guard constructor.

### Trust anchors and evidence-gated attachment conditioning

Both trust decision sites (`prompts/simclient/planner_system.jinja2` step 4 and
`FAITHFUL_PROMPT`) now carry the appendix C.4 trust-level anchors mapped onto the
sandbox 0-1 trust, plus an explicit rule that a trust level changes amplitude and
form only and never the disclosure permission.
`ClientProfile.attachment_conditioning()` returns pattern guidance only when the
pattern is `anxious`, `avoidant` or `disorganized` **and**
`ClientRelationalProfile.source_fact_ids` is non-empty, resolves to existing
evidence nodes, and `confidence >= 0.5`. Otherwise the planner payload carries
`null` and both prompts require neutral handling. The PsychEval compiler leaves
`attachment_pattern` at `unspecified`, so this branch is inert in current
production runs and activates only for explicitly sourced profiles. The
conditioning is prompt-level guidance for `trust_change` only: it is not case
evidence, does not alter disclosure permission and never enters counselor memory.

### Optional local semantic topic matcher

`SemanticActivationMatcher` is a second `ActivationMatcher` implementation,
selected by `client.topic_matcher: semantic` (default `tags`). It scores the
fraction of a tag's character unigrams and bigrams that occur in the counselor's
message (`DEFAULT_THRESHOLD = 0.4`), which recovers morphological variants such
as "同事关系" from "我和同事之间的关系" that the exact tag matcher misses. It is
deliberately local: no extra API call, no transport failure mode and no
unauditable model rationale, but also no paraphrase, negation or cross-language
resolution. Trust gating, session scope, dependencies, ambiguity handling and the
single-low-information-tag guard are unchanged, and the selected value is
recorded in the trajectory snapshot. The reference's LLM topic extraction is
therefore approximated rather than reproduced; a model-based matcher still needs
its own audit trail and cost accounting.

| Files | Change / purpose | Verification |
| --- | --- | --- |
| `runtime/dialogue_guard.py`, `agents/counselor.py`, `runtime/orchestrator.py` | Client idling cues, direction-change repair and hand-over, previous turn signals passed to the counselor | Cue and threshold boundaries, single-cue rejection, counselor repair/hand-over, existing dialogue-loop test |
| `domain/models.py`, `agents/client.py`, `client_simulation/policies.py`, `prompts/simclient/planner_system.jinja2`, `client_simulation/prompts.py` | Evidence-gated attachment conditioning, appendix C.4 trust anchors in both trust decision sites, prompt version v7 | Inert unsourced gate, evidence/confidence/pattern gate, planner payload and rendered-prompt checks, faithful trust step |
| `runtime/disclosure.py`, `runtime/__init__.py`, `domain/models.py`, `config.py`, `configs/runtime.yaml`, `runtime/orchestrator.py` | Optional local semantic matcher, explicit configuration and trajectory record | Tag-versus-semantic activation ablation, trust gating unchanged, low-information guard, factory/config wiring |
| `tests/test_dialogue_loop.py`, `tests/test_client_mechanism_boundaries.py`, `tests/test_components.py` | 15 new cases plus the prompt-version assertion | Full suite **500 passed** |

## Risks, omissions and smallest next steps

- Coefficients are engineering hypotheses, not clinically validated effects.
  Boundary tests prove information flow and state accounting, not realism or
  therapeutic efficacy. Real API experiments and independent review remain.
- Topic matching is lexical, not semantic. Appraisal combines structured model
  reactions, approved disclosure cost and Chinese boundary/pressure markers;
  negation, quoted speech and other languages can be misclassified. The optional
  `semantic` matcher only widens character n-gram overlap for tags that are
  literally present in another form; it is not a semantic model and remains
  untested against real paraphrases.
- The idling guard is a text/cue heuristic. Its thresholds are engineering
  hypotheses, its marker list is Chinese-only, and a detected repair replaces one
  skill-based counselor turn exactly like the existing boundary guard. It cannot
  prove that a client has no content left, and it never changes client planning or
  disclosure permission.
- Attachment conditioning is prompt-level and currently inert for compiled
  PsychEval profiles, which never set an evidence-backed `attachment_pattern`.
  Trust asymmetry is therefore guided, not enforced in state, and using it in a
  reported experiment requires a case set that actually carries sourced attachment
  evidence plus expert review of the anchors.
- The no-pipeline compatibility path does not separately assess trust after the
  free response. Isolating behavior from trust needs an independent trust switch
  or critic; doing so would add an API call and change the historical baseline.
- Atom substantiation/leakage checks are textual and cannot prove semantic
  non-disclosure or detect every paraphrase. Spoken fragments are preserved, but
  the existing ID ledger treats a partially disclosed atom as disclosed; remainder
  retrieval and fragment-level dependency readiness need a separate design.
- Counselor E.7/E.8/E.9 consolidation retains its existing limitations documented
  in `MEMORY.md`; new simulation controls are never supplied to those prompts.
- Resistance still resets at session boundaries by the existing tested contract;
  rupture now persists. A gradual resistance-retention experiment needs its own
  explicit configuration and comparison, not an implicit contract change.
- No new emotional labels, Big Five inference, additional topic extraction API,
  model migration, distillation or local model deployment is implemented. The
  `semantic` topic matcher stays local to keep that boundary.
- Do not pool runs made under different prompt/state behavior. First use a fixed
  case set to compare full/ablation modes with repeated samples, report leakage,
  ambiguity, disclosure rate, trust/emotion trajectories and model-call cost;
  then consider evidence-based appraisal and fragment-aware disclosure.

## Test record

The global Anaconda interpreter lacked `openai`: initial `pytest -q` returned
393 passed, 4 failed, 63 setup errors, 1 skipped. The existing project `.venv`
already contained the declared dependencies. Its clean baseline was
`./.venv/Scripts/python.exe -m pytest -q`: **461 passed**.

Final validation uses that same project interpreter, with all outputs confined
to the existing per-invocation `runs/tests` convention. No real API call,
existing run deletion or shared-runtime database migration was performed.

Final `./.venv/Scripts/python.exe -m pytest -q`: **477 passed in 102.41s**,
including 16 added boundary cases. `git diff --check` passed. Intermediate
new-test construction failures were repaired, and an attempted resistance
retention change was withdrawn to preserve the existing session contract;
no existing assertions were weakened to accept it.

### Second round record (2026-10-07)

Before the second round the same interpreter reported **485 passed in 43.92s**
(a 2026-10-03 snapshot that `ROADMAP.md` has since replaced with the current
500-item count; the 477 above is the older first-round snapshot, not a
contradiction). After the three checklist items and their 15 new tests, the same
interpreter reports **500 passed in 42.55s**, with `--collect-only -q` also at
500. The count basis in `README.md`, `ROADMAP.md` and this file is now identical.

Added tests: idling cues and thresholds (5), counselor idling repair and
hand-over (2), semantic topic matcher ablation and factory/config wiring (4),
attachment-conditioning gate and prompt anchors (4). No real API call, run
deletion or shared-runtime database migration was performed; outputs stayed in
the per-invocation `runs/tests` directory and were auto-cleaned.
