# Psychological Counseling Simulation

This context models source-grounded simulated clients across multiple therapy sessions while keeping private case evidence separate from counselor-visible memory.

## Language

**Case Evidence**:
A source-grounded fact extracted from a PsychEval case and carrying an auditable source path and source text.
_Avoid_: Hidden memory, generated fact

**Disclosure Item**:
One semantically complete case-evidence unit that may become speakable when its activation, dependency, session-scope, and trust conditions are satisfied.
_Avoid_: Disclosure layer, sentence tier

**Spoken Evidence**:
Case evidence that the simulated client has actually expressed in generated dialogue and that passed disclosure verification.
_Avoid_: Retrieved fact, planned disclosure

**Memory**:
Counselor-visible longitudinal information built only from spoken evidence, session summaries, confirmed goals, and unresolved topics.
_Avoid_: Full profile, private case

**Interaction Prior**:
An evidence-backed expectation or coping tendency used to plan client reactions; it is a simulation prior, not a diagnosis or independently discloseable fact.
_Avoid_: Personality diagnosis, attachment label

**Therapy Formulation**:
The native BT, CBT, HET, PDT, or PMT conceptualization supplied by PsychEval.
_Avoid_: 5Ps

**5Ps View**:
An auditable cross-therapy causal projection of case evidence that supplements but never replaces the therapy formulation.
_Avoid_: Canonical formulation, second profile
