# Third-party notice

This research sandbox adapts data structures, benchmark cases, hierarchical skills and evaluation prompts from [PsychEval](https://github.com/ECNU-ICALK/PsychEval), pinned for reproducible conversion at revision `e04df535749e5bca76fcc45d9a85f3f46a082d91`. Additional bundled profile assets were copied from the local Psych-new research tree; their presence does not imply that the current runtime loads them.

PsychEval materials are licensed under CC BY-NC 4.0. Local code adds normalized Pydantic fields, deterministic case-level splits, source-grounded disclosure layers, stable therapy-prefixed skill identifiers and provenance manifests. Original atomic `skill_id` values are preserved. Use is restricted to non-commercial teaching and research.

The experience and skill-evolution design is informed by the PsychAgent paper and AutoSkill/SkillEvo. This repository does not claim to reproduce an unpublished PsychAgent training repository. No AutoSkill source code is currently vendored; future copied or adapted MIT code must retain its notice and stay behind an adapter.

The optional probability-weighted (logprob) scale scoring adapts the methodology of Eq. 8 in Zhang et al., *Mechanistic control of large language models as simulated participants via linear representation* (npj Artificial Intelligence, DOI 10.1038/s44387-026-00160-9): a judge's numeric token distribution is aggregated into a continuous rating behind a refusal quality gate. No upstream code, weights or data are vendored; the scoring request, prompt asset and diagnostics are this repository's own implementation over the existing PsychEval instruments. See `notes/logprob_scoring_borrowing.md`.
