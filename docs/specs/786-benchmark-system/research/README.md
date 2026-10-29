# #786 research

Supporting material behind [`../design.md`](../design.md). Not requirements: `ak-dev-review-pr` does not extract
requirements from this folder.

The content is distilled from the team's benchmarking design notes (kept outside the repo). External facts (cloud
scaling behaviour, metric resolutions, billing rules, API names) were checked against the official docs on
2026-10-20 to 2026-10-23 when those notes were written; each file lists its sources. They were **not re-checked** for
this spec, so re-verify a fact before code depends on it. Repo facts (Terraform defaults, Helm values, AK code) were
re-checked against `develop` on 2026-10-25 and carry `path:line`.

| File | Takeaway | Status |
|---|---|---|
| [platform-scaling-and-cost.md](platform-scaling-and-cost.md) | How each host scales and bills, which API or metric reads worker counts and cost, and what that means for step length and resolution | External facts verified 2026-10-20..23, repo facts 2026-10-25 |
| [reading-the-results.md](reading-the-results.md) | Caveats and expected effects (bottlenecks outside AK, clock offsets, fetcher disagreement, run length) for people reading the graphs. Never to be detected or fixed by the benchmark | Notes only |
