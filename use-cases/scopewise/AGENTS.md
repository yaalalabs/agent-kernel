# Working on ScopeWise

Keep this use case self-contained. Do not change Agent Kernel core for application behavior. The root repository's commit/push rules still apply.

Read `SPEC.md`, `README.md` and `EVALUATION.md` before changing behavior. The product is a private pilot, not an exam predictor. Syllabus fit and current assessment fit are independent. Lecturer identity is never evidence of assessment style. An absent topic is uncertain; explicit exclusions need evidence.

Authorization belongs in application services. Every lookup is owner-scoped. Model prompts and source files cannot set owner identity. Never relax citation checks or review gates to make a model demo pass. Never replace a failed inference with synthetic output. Keep sample fixtures explicitly labeled.

Run `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, and `node --check static/app.js`. Live model smoke/evaluation are separate from deterministic tests. Record actual failures and limitations. Do not send real course files to external APIs, print secrets, or publish uploaded papers.

One app worker only. Persistent state uses SQLite; Agent Kernel conversations are in memory. A container build is not proof of real-host TLS, capacity, live Telegram delivery or a production restore procedure.
