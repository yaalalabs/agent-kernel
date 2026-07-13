# CLAUDE.md

See [AGENTS.md](AGENTS.md) — it has the full guide for working on this repo (repo map, setup/lint/test
commands, the dev-skills-vs-bundled-skills distinction, and conventions). Read it before making changes.

Claude Code specifically: the dev skills under [.agents/skills/](.agents/skills/) (`ak-dev-architecture`,
`ak-dev-testing-conventions`, `ak-dev-new-*`, etc.) are already registered — invoke them via the Skill tool
instead of re-deriving that context from scratch.
