# Third-party licenses

- PsychEval data, skills, prompts and repository materials: CC BY-NC 4.0. See
  <https://creativecommons.org/licenses/by-nc/4.0/> and the upstream `LICENSE` obtained by
  `psych-sandbox data fetch psycheval`.
- AutoSkill/SkillEvo: MIT. No upstream source code is currently vendored here.

Bundled runnable cases live in `data/<therapy>/`; retained source-reference profiles live in `assets/profiles/`. When the optional converter runs, generated files retain their source revision and SHA-256 digest in `data/processed/psycheval/manifest.json`, an ignored and rebuildable directory.
