# Client simulation audit and implementation

Audited on 2026-10-02 against the local source at `D:/PatientHub-master`.
That directory has no Git metadata, so this comparison identifies files rather
than claiming a verified upstream revision or paper reproduction.

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
the existing profile/trace versions remain 4/5. Prompt behavior is versioned v6.

## Research configuration

The YAML `client` block supports `policy: compact_patientact` or
`faithful_patientact`, plus `use_memory`, `use_pipeline`, `use_trust_gating`.
All three switches default to true. Direct Python configuration uses the
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

`profile.simulation_config` is private, persisted simulation configuration.
Traits are never automatically inferred from PsychEval. Uncertainty 1.0 makes
all modifiers zero; lower uncertainty allows at most 0.1 expression preference
or 0.05 threat/recovery adjustment. Expression is prompt-level guidance;
threat/recovery actually scale state deltas. Legacy excluded personality is not
silently promoted. No personality-based disclosure-threshold offset is added.

## Risks, omissions and smallest next steps

- Coefficients are engineering hypotheses, not clinically validated effects.
  Boundary tests prove information flow and state accounting, not realism or
  therapeutic efficacy. Real API experiments and independent review remain.
- Topic matching is lexical, not semantic. Appraisal combines structured model
  reactions, approved disclosure cost and Chinese boundary/pressure markers;
  negation, quoted speech and other languages can be misclassified.
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
  model migration, distillation or local model deployment is implemented.
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
