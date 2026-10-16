# #803: Decisions log

Decisions taken during the review of [design.md](../design.md), kept here so the design itself stays
requirements only. Each line names the decision; the design section it shaped is in brackets.

## Phase 1

- **Credential resolution:** the two credentials AK reads itself (`LOGFIRE_READ_TOKEN`,
  `TRACELOOP_API_KEY`) go through `SecretManager`; the ones the provider SDKs read stay environment
  variables, as on the send side. [§Configuration]
- **Contract test suite:** shipped now, because bring-your-own tracers can fetch. [§Tracer interface]
- **Shared fetcher base:** paging, dedupe and limit accounting live once in `TraceFetcher`, not in four
  copies. [§Tracer interface]
- **Local filter check:** every fetcher runs `TraceQuery.matches`, not only the approximate ones, so no
  provider's boundary rule leaks into the result. [§Tracer interface]
- **Traceloop kind filter:** none server-side. A kind can come from `gen_ai.operation.name` or
  `traceloop.span.kind`, and the `filters` API has no OR across ids. [§Traceloop fetcher]
- **Traceloop support level:** documented as best effort.
- **Fetch-only processes:** keep `Trace.get()` running the send-side `init()`; it validates credentials
  early.
- **Limit semantics:** when more spans match than `limit`, the newest `limit` are kept. "Oldest first" is
  only the order of the returned list.
- **CloudWatch span classification:** left as is; the run span stays `span`.
- **Langfuse metadata truncation:** fixed with `expand_metadata=attributes`.
- **Live verification:** run by the change's author against real accounts before merge.
- **CloudWatch spans outside `aws/spans`:** `aws/spans` stays the only source; the requirement is
  documented, and a missing log group raises `AKConfigError`. [§CloudWatch fetcher]
- **Logfire session id unscrubbed, not opt-in:** Langfuse, Traceloop and CloudWatch already export it as
  given; the docs tell users to keep personal data out of session ids. [§Logfire fetcher]
- **Langfuse flush scope:** `run()` only. No tracer wraps `stream()` today (CloudWatch's flush is
  `run()`-only too); wrapping it is a separate change for all four. [§Langfuse flush]

## Phases 2 and 3

- **Langfuse flush in AK core:** yes, done in Phase 1.
- **Results retention:** 90-day TTL.
- **Where grading runs:** in the agent's own AK serverless Lambda, behind `/eval` and `/check`, with no
  scheduled job.
- **`TraceCase` vs `AKEvaluationCase`:** kept separate. `TraceCase` groups a trace's spans and holds the
  stored, unjudged facts; `TraceEvaluationCase` is what the judges read.
- **CI role permissions:** none new. Terraform creates only resource types the weekly run already
  creates through the AK module: a DynamoDB table with TTL (`ak-deployment/ak-aws/serverless/state.tf:335`)
  and an inline role policy (`state.tf:434`). The test step makes only HTTP calls.
- **When is a trace complete?** No provider says. The job grades a trace only when its root span finished
  at least 2 minutes ago (the parent check was dropped in the follow-up below). Remaining risk: a span arriving
  more than 2 minutes late, which affects only that trace's scores. [§Evaluation run]
- **Session index projection:** `INCLUDE` (`progress`, `error`, `updated_at`), so the index holds no
  second copy of `spans_gz`. [§Table]
- **Where trace config lives:** `config.yaml` (`trace.enabled`, `trace.type`), not Lambda environment
  variables. [§Deployment]

## Follow-up: whole traces and span status

Taken while simplifying what the example writes. The rule behind most of them: AK maps each provider's fields
onto neutral ones but doesn't patch over a provider's own mistakes, and user code trusts what the fetcher returns.

- **Span kind:** the example uses `span.kind` and no longer re-classifies with `OTelSpanClassifier`. Fixing it in
  the Langfuse fetcher (fall back to the classifier when the type is `SPAN`) was rejected: a `kinds=[TOOL]` query
  could no longer filter by `type=TOOL` server side and would page through every span in the window. Accepted
  risk: a tool span Langfuse labels `SPAN` is missing from the transcript; check with one live run.
  [§Span kinds]
- **Trace assembly in AK:** `Trace.fetch_traces` and `FetchedTrace` take over the grouping, the root finding and
  the usage sum, because every trace evaluator needs them. `fetch_spans` (the renamed `fetch`) stays. [§Public API]
- **Single pass, partial traces:** `fetch_traces` fetches the window's spans once and groups them. Two passes (find
  the trace ids, then fetch each trace whole) always return whole traces but cost a second call, and one request
  per trace id on Langfuse. A partial trace at the window's edge is fine: a tracer's own UI shows the same while
  spans are landing. [§Result model: `FetchedTrace`]
- **Filters:** `fetch_traces` reuses `TraceQuery`; `kinds` and `name` select single spans, so they raise
  `ValueError` and users filter `trace.spans`.
- **A trace with no root is returned with `root=None`**, not dropped: dropping hides data silently, and a caller
  summing cost over a window still wants those spans. The example skips it (counted as `no_root`); the next
  `/eval` fetches it again.
- **Traceloop root:** AK's Traceloop runners add no wrapper span, so `trace.user_input` / `trace.output` are
  empty there. No wrapper is added; documented.
- **Fetch limit check dropped:** a demo session never reaches the default 1000 spans, so the example no longer
  raises on a full result.
- **`status: SpanStatus`, not `failed: bool`:** `level` is Langfuse's own field. `UNSET` / `OK` / `ERROR` follow
  the OTel span status, and each fetcher maps its provider's field onto it.
- **Readiness stays the caller's:** AK returns what the tracer has stored. The settle time, the `pending` /
  `unfinished` states and the retry loop stay in the example; `spans_missing_parent` and the fetch limit check
  went.
- **Opik judges stay in the example:** an attempt to move the four reference-free judges into AK's Opik
  evaluator was reverted. `OpikTraceEvaluator` stays in the example, and AK's evaluator is unchanged.
- **Not changed:** the Langfuse fetcher's kind mapping, the Traceloop runners, the async self-invoke in `api.py`,
  the DynamoDB store, `_as_text`, and `lambda_test.py`.
