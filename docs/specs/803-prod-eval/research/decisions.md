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
  at least 2 minutes ago and every span's parent is present. Remaining risk: a leaf span arriving more
  than 2 minutes late, which affects only that trace's scores. [§Evaluation run]
- **Session index projection:** `INCLUDE` (`progress`, `error`, `updated_at`), so the index holds no
  second copy of `spans_gz`. [§Table]
- **Where trace config lives:** `config.yaml` (`trace.enabled`, `trace.type`), not Lambda environment
  variables. [§Deployment]
