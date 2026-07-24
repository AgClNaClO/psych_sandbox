# Third-party notice

This research sandbox adapts data structures and benchmark cases from
[PsychEval](https://github.com/ECNU-ICALK/PsychEval), revision
`e04df535749e5bca76fcc45d9a85f3f46a082d91`.

PsychEval is licensed under CC BY-NC 4.0. Local conversion adds normalized
Pydantic fields, deterministic case-level splits, derived meta-skill identifiers,
simulation-only Big Five priors, and provenance manifests. Original atomic
`skill_id` values are preserved. Use is restricted to non-commercial teaching
and research.

The design of later experience replay and skill evolution is informed by the
PsychAgent paper and AutoSkill/SkillEvo. No claim is made that this repository
reproduces an unpublished PsychAgent training repository. Any future AutoSkill
code copied or adapted must retain its MIT notice and be isolated behind an
adapter.
