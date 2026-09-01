# ScopeWise competition evidence

ScopeWise turns old papers into evidence-based practice for the module a student is studying now. It supports **SDG 4: Quality Education** by reducing time spent on questions that are too shallow, too advanced, explicitly excluded, or incompatible with current answer-format guidance.

The winning claim is narrow and demonstrable: ScopeWise makes curriculum change inspectable. It independently judges syllabus fit and current assessment fit, records which accepted change invalidated earlier work, and keeps the student as the final reviewer.

## Rubric matrix

| Scoring category | Evidence in the repository | Five-minute demo moment |
| --- | --- | --- |
| Idea and use-case value — 40% | [README.md](README.md) defines the real student problem, the two independent judgments, lecturer-change uncertainty, SDG 4, local RAG, and private pilot limits. [SPEC.md](SPEC.md) defines evidence and review invariants. | 0:00–0:40: contrast a syllabus-relevant definition question, an explicitly excluded BCNF proof, and an unsupported indexing question. |
| Agent Kernel usage — 30% | [`scopewise/agents.py`](scopewise/agents.py) registers three agents with `PydanticAIModule`; all runs use `AgentService`; tools take identity from `ToolContext`. [`scopewise/telegram.py`](scopewise/telegram.py) subclasses `AgentTelegramRequestHandler`. Saved provenance shows the registered alignment agent without revealing internal prompts or identities. | 2:10–3:10: show a completed local comparison's run details, then ask “What changed?” so `get_change_impact` runs through the assistant. 4:10–4:40: use the same assistant in a live private Telegram chat if configured. |
| Working solution — 20% | [`scripts/judge_check.py`](scripts/judge_check.py) runs deterministic submission checks. Tests cover ownership, evidence, jobs, candidate selection, provenance, change impact, API behavior, Telegram, and responsive UI contracts. [DEPLOYMENT.md](DEPLOYMENT.md) and the container files define the single-worker private pilot. | 0:40–2:10: load the synthetic sample, change the lecturer, inspect the impact card, reconfirm current guidance, and review both judgments. 3:10–4:10: correct one decision and build/export a pack with coverage gaps. |
| Documentation — 10% | [README.md](README.md) contains the required problem, solution, setup, run, Agent Kernel, and verification sections. [DEMO.md](DEMO.md) is timed below five minutes. [EVALUATION.md](EVALUATION.md) records measured failures and unverified release gates. [AGENTS.md](AGENTS.md) and [SPEC.md](SPEC.md) constrain future changes. | 4:40–5:00: point judges to the one-command check and state the current model, Telegram, and deployment limitations honestly. |

## Differentiators judges can verify

- **Change impact, not change prediction:** a lecturer change withdraws assessment-guidance approval and makes dependent analyses and packs stale. The UI explicitly says identity does not prove the paper changed.
- **Exclusion-first hybrid candidate selection:** keyword overlap always keeps direct explicit exclusions; local embeddings may add relevant required objectives but cannot certify a match.
- **Inspectable Agent Kernel execution:** each saved comparison records the registered agent, retrieval mode, bounded candidate counts, guidance-excerpt count, discarded aliases, and human-review gate.
- **Small-course local RAG without a paid vector service:** page/slide chunks, embeddings, exact citations, and metadata stay in SQLite. Ollama failure falls back to keyword search.
- **Useful failure behavior:** unknown aliases become an uncertain judgment; malformed or incomplete results are rejected; manual evidence review stays available and is labeled.
- **One reviewed artifact:** the pack removes exact repeats, retains citations and the two judgments, and lists objectives that still lack suitable practice.

## Submission checklist

- [x] Work is isolated under `use-cases/scopewise/`; Agent Kernel core is unchanged.
- [x] Fork remote points to `https://github.com/chirana07/agent-kernel.git`.
- [x] Problem, solution, setup, run, Agent Kernel usage, and verification are explicit in the README.
- [x] Original synthetic sample material is clearly labeled and safe to record.
- [ ] Confirm every registered teammate has completed the official team form and uses the required team ID.
- [ ] Confirm every teammate has starred the upstream Agent Kernel repository as required by the competition booklet.
- [x] Run `python -m scripts.judge_check --full` on the final submission commit.
- [ ] Push the final competition branch and follow the official submission instructions.
- [ ] Record a live Telegram interaction through a real bot and HTTPS endpoint. Deterministic adapter tests do not satisfy this box.
- [ ] Verify a public HTTPS deployment. A local/container smoke test does not satisfy this box.

Do not mark the last two boxes complete from screenshots, mocks, or simulated webhook calls. Do not describe the development regression as an accuracy benchmark.
