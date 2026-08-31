# Separate PsychEval case truth from PatientAct client policy

PsychEval is the sole source of case evidence, native therapy formulation, and longitudinal session structure, while PatientAct-style mechanisms govern activation, trust-gated disclosure, reaction, behavior, resistance, and utterance generation. This avoids turning synthetic attachment or personality seeds into case facts and keeps the five therapy formulations intact behind the existing `ClientSimulator.respond` interface.
