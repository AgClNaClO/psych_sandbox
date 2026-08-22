# Issue tracker: GitHub

Issues and specifications for this repository live in GitHub Issues. Run `gh` commands inside this checkout so
the `origin` remote selects `AgClNaClO/psych_sandbox` automatically.

## Read operations

- Read one issue and comments: `gh issue view <number> --comments`.
- List open issues: `gh issue list --state open --json number,title,body,labels,assignees`.
- Resolve an ambiguous `#42`: try `gh pr view 42`; if absent, use `gh issue view 42 --comments`.
- Inspect repository labels before applying one: `gh label list --limit 100`.

## Write operations

- Create: `gh issue create --title "..." --body-file <markdown-file>`.
- Comment: `gh issue comment <number> --body-file <markdown-file>`.
- Label: `gh issue edit <number> --add-label "<label>"`.
- Close with rationale: `gh issue close <number> --comment "..."`.

Repository pull requests are code-review surfaces, not the default feature-request intake. Use `gh pr view` and
`gh pr diff` for review; create an issue when a new request needs specification or tracking.

When a workflow asks for a canonical triage state, read `docs/agents/triage-labels.md` first. Completion means
the selected label exists on GitHub and the issue comment records any nuance lost by the compatibility mapping.
