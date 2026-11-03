# Agent Kernel OpenAI Agents with Langfuse Trace Evaluation in AWS Serverless (Lambda)

This example grades an agent on its real traffic. An OpenAI Agents SDK agent runs on AWS Lambda with Langfuse
tracing. When you call `/eval`, the example reads the session's traces back through Agent Kernel, scores each
request with four Opik LLM judges, and stores one row per request in DynamoDB.

## What Agent Kernel does, and what the example writes

| Agent Kernel | The example |
|---|---|
| Traces every request to Langfuse from `config.yaml` (`trace.type: langfuse`) and flushes the spans before the Lambda freezes. The agent has no tracing code. | The agent itself (`lambda_agent_runner.py`). |
| Reads the traces back with one call, `Trace.get().fetch_traces(session_id=..., last=...)`. Each `FetchedTrace` already holds the request, the answer, the tool spans, the agents that ran and the token usage. The example never calls Langfuse's own API. | `TraceCase` (`evaluator/case.py`): turns a `FetchedTrace` into the text the judges read. |
| Defines how an evaluator looks: `AKEvaluator`, its input `AKEvaluationCase`, its verdict `AKEvaluationResult`, and the judge model in `AKTestConfig` (`AK_TEST__LLM__*`). | `OpikTraceEvaluator` (`evaluator/opik_evaluator.py`): the judges. AK's built-in evaluators need an expected answer, which production traffic doesn't have, so the example writes its own. |
| Serves the API on Lambda (`Lambda.register`, `Lambda.handler`) and runs the agent in queue mode. | When grading runs (`/eval`), where results go (DynamoDB) and how they are read (`/check`). |

Every place the code relies on Agent Kernel has a comment starting with `Agent Kernel:`, so you can list them:

```bash
grep -rn "Agent Kernel:" --include=*.py --include=*.yaml .
```

The heart of it is `SessionGrader.grade_session` (`evaluator/grader.py`), shortened here:

```python
traces = Trace.get().fetch_traces(session_id=session_id, last=self.FETCH_WINDOW)  # Agent Kernel
for trace in traces:
    case = TraceCase.from_trace(trace)
    evaluation_case = case.to_evaluation_case(OpikTraceEvaluator.THRESHOLD)
    results = [evaluator.evaluate_by_llm(evaluation_case) for evaluator in self._evaluators
               if evaluator.applies_to(evaluation_case)]
    self._store.save_results(case, results)
```

`fetch_traces` returns the same `FetchedTrace` shape for Langfuse, Logfire, OpenLLMetry and CloudWatch, so the
grading code doesn't depend on the tracer's own API. What each tracer records still differs a little (see
"Changing the metrics or the store").

## The flow

1. **Send 3 requests.** `simulate_traffic.py` sends three questions to the agent under one session. Each
   request is one trace in Langfuse.
2. **Wait about 2 minutes** for Langfuse to store the traces.
3. **Call `POST /eval`** with the session id. It invokes the request-handler Lambda asynchronously with
   `{"action": "START_GRADE", "session_id": ...}` and returns `202` right away.
4. **The `START_GRADE` invocation grades the session.** It fetches the session's traces from the last hour
   with `Trace.get().fetch_traces(session_id=..., last=1h)`, runs four Opik judges on each one, and writes one
   row per trace to DynamoDB.
5. **Wait about 3 minutes.**
6. **Call `GET /check`** with the session id. It returns the session's graded rows. Three rows means every
   request was graded.

## Architecture

```
              POST /chat                                                 spans (flushed before the Lambda freezes)
client ──▶ request handler ──▶ SQS input ──▶ agent runner ──────────────────────────────────────▶ Langfuse
                 ▲                               │ reply                                             │
                 └── response store ◀── response handler ◀── SQS output                              │
                                                                                                     │
              POST /eval {"session_id"}                                                              │
client ──▶ request handler ── async invoke {"action": "START_GRADE"} ──▶ request handler             │
                                                                             │ fetch_traces ◀────────┘
                                                                             │ 4 Opik judges per trace
              GET /check?session_id=...                                      ▼
client ──▶ request handler ───────── query by session ──────────────▶ DynamoDB (one row per trace)
```

The deployment runs in queue mode (`queue_mode = true`, `execution_mode = "rest_sync"`), with three Lambdas:

| Lambda | Entry point | What it does |
|---|---|---|
| Request handler | `lambda_request_handler.handler` | Serves `/chat` (through `Lambda.handler`), `/eval` and `/check`, and runs the grading when it receives `START_GRADE`. It is the only tier that carries Opik. |
| Agent runner | `lambda_agent_runner.handler` | Runs the agent (`ServerlessAgentRunner`): a `triage` agent that hands order questions to a `support` agent with a `get_order_status` tool. Its Langfuse runner sends the trace and flushes it before the Lambda freezes. |
| Response handler | `lambda_response_handler.handler` | Stores each reply in the response store (`ResponseHandler`). |

The session and response stores use the Redis cluster of the base `openai` deployment (`config.yaml`).

| Route | What it does |
|---|---|
| `POST /api/v1/chat` | The agent under evaluation. Each request is one trace. |
| `POST /api/v1/eval` | Body `{"session_id": "..."}`. Starts the grading in an asynchronous self-invocation and returns `202`. |
| `GET /api/v1/check` | Query `session_id`. Returns `graded` (the number of rows) and the rows themselves. |

`lambda_request_handler.handler` checks for `START_GRADE` before handing the event to `Lambda.handler`.
`START_GRADE` is a plain Lambda event, not an API Gateway request, so only the Lambda's own invocation can
start a grading. It runs within the request handler's 10-minute timeout, not API Gateway's 29 seconds.

The example has no retries and keeps no progress state: a judge call that fails stops the grading, so that
trace and any after it get no row and `/check` reports fewer than three.

> **Warning:** the routes have no authorizer, like the base `openai` example. Anyone with the URL can call `/eval`,
> and every call spends OpenAI tokens on the LLM judges. Destroy the stack when you're done, or put an authorizer
> (or an API key) in front of the API before leaving it deployed.

## The code

| File | What it does |
|---|---|
| `lambda_request_handler.py` | Registers `/eval` and `/check`, and sends `START_GRADE` events to the grading. |
| `evaluator/api.py` | `EvaluationAPI`: the `/eval` and `/check` routes, and the `START_GRADE` entry point. |
| `evaluator/grader.py` | `SessionGrader`: fetches the session's traces, runs the judges, saves one row per trace. |
| `evaluator/case.py` | `TraceCase`: one request's input, answer, tool calls and token usage, read from its spans. |
| `evaluator/opik_evaluator.py` | `OpikTraceEvaluator`: an `AKEvaluator` that scores one metric with an Opik judge. |
| `evaluator/store.py` | `EvaluationStore`: writes and reads the DynamoDB rows. |

The example writes its own Opik evaluator, so it declares `opik` in its own `pyproject.toml` (the
`request_handler` extra) rather than using Agent Kernel's `opik` extra.

## Metrics

All four are Opik LLM judges on `gpt-4.1-mini` (`AK_TEST__LLM__PROVIDER` / `AK_TEST__LLM__MODEL`), with
threshold `0.5`. None needs an expected answer.

| Metric | Opik metric | Reads | Runs when | Passes when |
|---|---|---|---|---|
| `task_completion` | `AgentTaskCompletionJudge` | the transcript (request, tool calls, answer) | always | score ≥ 0.5 |
| `tool_correctness` | `AgentToolCorrectnessJudge` | the transcript | the trace has a tool call | score ≥ 0.5 |
| `answer_relevance` | `AnswerRelevance` | input, output | always | score ≥ 0.5 |
| `hallucination` | `Hallucination` | input, output, tool results as context | always | score **<** 0.5 |

Tool calls, latency, tokens and cost come from the spans and are stored, not judged.

The judges see the request, the tool calls and the answer, but not the agent's instructions, so they score a
reply against what the user asked for. A correct refusal therefore fails: the off-topic question ("Write me a
poem about the ocean.") is declined as the triage agent is told to, and its row has `passed` false, with
`task_completion` and `answer_relevance` near 0. To grade against your own rules, give the judges the agent's
instructions (for example as `hallucination` context) or add a rubric metric such as Opik's `GEval`.

## The results table

`<prefix>-trace-evaluations`, partition key `trace_id`, with a `session_id-index` and a 90-day TTL on
`expires_at`. One row per graded trace:

| Attribute | Meaning |
|---|---|
| `trace_id`, `session_id`, `started_at`, `latency_ms`, `evaluated_at` | the trace and when it was graded |
| `input`, `output`, `agents`, `tool_calls` | the request, the answer, the agents that ran and each tool call |
| `input_tokens`, `output_tokens`, `total_tokens`, `cost` | `usage` summed over the trace's spans |
| `task_completion`, `tool_correctness`, `answer_relevance`, `hallucination` | a map: `score`, `threshold`, `passed`, `reason`, `higher_is_better` |
| `passed` | true when every metric passed |

Text fields are cut to 4,096 characters.

## Changing the metrics or the store

- **Metrics:** add an entry to `OpikTraceEvaluator.METRICS` and `_JUDGE_CLASSES`
  (`evaluator/opik_evaluator.py`). For another judge library, write another `AKEvaluator` subclass with
  `applies_to` and `evaluate_by_llm`, and build it in `SessionGrader.__init__`.
- **Store:** `SessionGrader` and `EvaluationAPI` only call `save_results` and `list_session_results` on
  `EvaluationStore` (`evaluator/store.py`); replace it with a class offering the same two methods.
- **Tracer:** `Trace.fetch_traces` works for Langfuse, Logfire, OpenLLMetry and CloudWatch. This example is built
  and tested on Langfuse, which sets the session id on every span. On Traceloop the root span carries no input or output,
  so `trace.user_input` and `trace.output` are empty there.

## Prerequisites

- AWS CLI configured with appropriate credentials, Docker running, and Terraform `1.9.5` or higher.
- A Langfuse project (Langfuse Cloud or self-hosted) and its public and secret keys.
- The base VPC, security groups and Redis cluster from the `openai` example (`cd ../openai/deploy && ./deploy.sh`).

## Deploy

1. Get the VPC ID, private subnet IDs and the three security group IDs from the openai deployment:
    ```bash
    cd ../openai/deploy && terraform output vpc_id
    cd ../openai/deploy && terraform output private_subnet_ids
    cd ../openai/deploy && terraform output request_handler_security_group_id
    cd ../openai/deploy && terraform output agent_runner_security_group_id
    cd ../openai/deploy && terraform output response_handler_security_group_id
    ```

2. Set the variables:
    ```bash
    export TF_VAR_openai_api_key=<OPENAI_API_KEY>
    export TF_VAR_langfuse_public_key=<LANGFUSE_PUBLIC_KEY>
    export TF_VAR_langfuse_secret_key=<LANGFUSE_SECRET_KEY>
    export TF_VAR_langfuse_base_url=https://cloud.langfuse.com  # the default; set it for another region or self-hosting
    export TF_VAR_vpc_id=<VPC_ID_FROM_OPENAI>
    export TF_VAR_private_subnet_ids='["<SUBNET_ID_1>", "<SUBNET_ID_2>"]'
    export TF_VAR_request_handler_security_group_id=<RQH_SG_FROM_OPENAI>  # optional, each of the three
    export TF_VAR_agent_runner_security_group_id=<AR_SG_FROM_OPENAI>
    export TF_VAR_response_handler_security_group_id=<RSH_SG_FROM_OPENAI>
    ```

3. Deploy. `deploy.sh` builds each Lambda's package from its `pyproject.toml` extra. The request handler
   (Opik) and the agent runner (OpenAI Agents SDK) are over Lambda's 250 MB zip limit, so Terraform builds
   them as container images and Docker must be running; the response handler is a zip. `./deploy.sh local`
   installs `agentkernel` from `../../../ak-py/dist` instead of PyPI:
    ```bash
    cd deploy && ./deploy.sh
    ```

## Try it

1. Send the example's three questions (an order lookup, an unknown order and an off-topic request) under one
   session. The script reads the URL from `AK_TEST_ENDPOINT` or the `agent_invoke_url` Terraform output,
   and prints the session id:
    ```bash
    uv run python simulate_traffic.py
    ```

2. Wait about 2 minutes for Langfuse to store the traces, then start grading:
    ```bash
    BASE=$(terraform -chdir=deploy output -raw agent_invoke_url | sed 's#/chat$##')
    curl -X POST "$BASE/eval" -H "Content-Type: application/json" -d '{"session_id": "<SESSION_ID>"}'
    ```

3. Wait about 3 minutes, then read the graded rows:
    ```bash
    curl "$BASE/check?session_id=<SESSION_ID>"
    ```

4. Or read the rows straight from DynamoDB:
    ```bash
    aws dynamodb scan --table-name "$(terraform -chdir=deploy output -raw results_table_name)" \
      --filter-expression "session_id = :s" \
      --expression-attribute-values '{":s": {"S": "<SESSION_ID>"}}'
    ```

## Test

The integration test sends one warm-up question under a throwaway session and waits 2 minutes, so Lambda cold
starts (which can outlast API Gateway's 29 s) hit it rather than the graded requests. It then sends the three
questions, waits 2 minutes, calls `/eval`, waits 3 minutes, and passes when `/check` reports 3 graded rows. It
runs in the weekly integration tests; locally:

```bash
AK_TEST_ENDPOINT=$(terraform -chdir=deploy output -raw agent_invoke_url) uv run --no-sync pytest lambda_test.py
```

It takes about 7 minutes, almost all of it waiting. It checks only that every request was graded and stored,
not the judges' verdicts.
