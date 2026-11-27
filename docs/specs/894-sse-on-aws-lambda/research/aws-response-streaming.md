# AWS response streaming: what the design rests on

Checked on 2026-11-26 against the AWS docs and the Lambda Web Adapter README. Each claim is marked
**verified** (read in the source named) or **unverified** (to be proven by the spike, see the end).

## Lambda

- **verified**: Python is not a native streaming runtime. "Lambda supports response streaming on
  Node.js managed runtimes. For other languages, including Python, you can use a custom runtime with
  a custom Runtime API integration to stream responses or use the Lambda Web Adapter."
  ([Lambda docs](https://docs.aws.amazon.com/lambda/latest/dg/configuration-response-streaming.html))
- **verified**: native Python streaming is still a roadmap request
  ([aws-lambda-roadmap#39](https://github.com/aws/aws-lambda-roadmap/issues/39)); no announcement found.
- **verified**: a streamed response can be up to 200 MB. The first 6 MB has uncapped bandwidth,
  then 2 MB/s.
- **verified**: "streamed responses are not interrupted or stopped when the invoking client
  connection is broken. Customers are billed for the full function duration."
- **verified**: "Lambda function URLs do not support response streaming within a VPC environment."
  The request-handler Lambda runs in the VPC (`state.tf:564-565`) to reach Redis/Valkey, so a
  Function URL is not an option.

## API Gateway REST API

- **verified**: streaming is set per integration with `responseTransferMode: STREAM` (default
  `BUFFERED`), for `AWS_PROXY` and `HTTP_PROXY` only, and for REST APIs only.
  ([transfer mode](https://docs.aws.amazon.com/apigateway/latest/developerguide/response-transfer-mode.html))
- **verified**: a Lambda proxy integration in `STREAM` mode uses the streaming invocation URI,
  `arn:aws:apigateway:<region>:lambda:path/2021-11-15/functions/<function-arn>/response-streaming-invocations`.
  ([Lambda proxy streaming](https://docs.aws.amazon.com/apigateway/latest/developerguide/response-streaming-lambda-configure.html))
- **verified**: the function must write the streaming proxy format: a JSON prelude (`statusCode`,
  `headers`, `multiValueHeaders`, `cookies` only), 8 null bytes within the first 16 KB, then the raw
  body. A function that does not conform gets a 500.
  ([format](https://docs.aws.amazon.com/apigateway/latest/developerguide/response-transfer-mode-lambda.html))
- **verified**: a stream can run for up to 15 minutes. The idle timeout (no data sent) is 5 minutes on
  Regional and private endpoints and 30 seconds on edge-optimized ones.
- **verified**: the first 10 MB is unthrottled, then 2 MB/s.
- **verified**: `STREAM` does not support endpoint caching, content encoding, or VTL response
  transformation.
- **verified**: the Terraform AWS provider pinned here (`6.70.0`, `ak-aws/serverless/main.tf:7`)
  exposes `response_transfer_mode` on `aws_api_gateway_integration` (checked from the provider
  schema for #978, PR #1005).
- **unverified**: whether a `REQUEST` Lambda authorizer works unchanged on a `STREAM` integration.
  None of the pages above mention authorizers.

## Lambda Web Adapter (LWA)

Source: [awslabs/aws-lambda-web-adapter](https://github.com/awslabs/aws-lambda-web-adapter) README.

- **verified**: LWA runs an ordinary web server inside Lambda and translates each invocation to an
  HTTP request to it. It can be used with managed runtimes, Python included.
- **verified**: `AWS_LWA_INVOKE_MODE=response_stream` turns streaming on (default `buffered`). The
  mode applies to the whole function.
- **verified**: zip packaging uses the layer
  `arn:aws:lambda:<region>:753240598075:layer:LambdaAdapterLayerX86:<version>` (or `...Arm64`), with
  `AWS_LAMBDA_EXEC_WRAPPER=/opt/bootstrap` and a start script as the handler. Image packaging copies
  `/lambda-adapter` into `/opt/extensions/`.
- **verified**: the port comes from `AWS_LWA_PORT` (default 8080, falling back to `PORT`). The
  readiness check uses `AWS_LWA_READINESS_CHECK_PATH` (default `/`).
- **verified**: it lists "Amazon API Gateway Rest API and Http API endpoints" as supported, and ships
  a "FastAPI with Response Streaming" example.
- **unverified**: whether the API Gateway request context (the authorizer's
  `requestContext.authorizer.principal`) reaches the app. The README names no header for it.
- **unverified**: that LWA in `response_stream` mode, behind a REST API `STREAM` integration, sends
  each SSE frame as it is written rather than in one block. This is the same claim PR #1005 lists as
  unverified for ECS.

## Spike (before `spec.md`)

One throwaway stack: a FastAPI `StreamingResponse` that writes a frame per second for 20 s, on Python
with the LWA extension (image), behind a Regional REST API `STREAM` integration with
`authorization = "NONE"`.

1. `curl -N` shows frames one second apart, not all at the end.
2. A run longer than 29 s completes.
3. The app sees the `Authorization` header unchanged (it authenticates the token itself).
4. The request path the app sees, so the path mapping in design section 3 is built on fact.

The two authorizer questions above (authorizer on `STREAM`, authorizer context through LWA) no longer
block the design: it puts no authorizer on this function (design section 5). They stay open only as
facts.

## Spike results (2026-11-26, us-east-2)

A throwaway stack: a Starlette app writing one frame per second for 40 s, zipped with the LWA layer
(`LambdaAdapterLayerX86:30`, `run.sh`, `AWS_LAMBDA_EXEC_WRAPPER=/opt/bootstrap`), behind a Regional REST
API `AWS_PROXY` integration in `STREAM` mode with the streaming invocation URI, `authorization = "NONE"`
and only `lambda:InvokeFunction` granted.

- **verified**: frames reach `curl -N` about one second apart, not in one block. Brief network stalls
  flushed up to four frames together once; this is jitter, not buffering.
- **verified**: the app receives the `Authorization` header unchanged.
- **verified**: `scope["path"]` is `/api/v1/chat`: the full path, with no stage prefix.
- **verified**: `lambda:InvokeFunction` is enough for the streaming invocation.
- **verified**: with `timeout_milliseconds` **unset**, the stream is cut after about 28 s (frame 28 of 40,
  no `done`). API Gateway applies its 29 s default.
- **verified**: with `timeout_milliseconds = 900000`, all 40 frames and `done` arrive, although the account
  quota "Maximum integration timeout in milliseconds" is 29000. `STREAM` honours an explicit timeout, and
  the quota does not block it. The design sets it explicitly.
- **lesson**: after the timeout change, one run still stopped at 28 s because the stage had not been
  redeployed; `aws apigateway create-deployment` fixed it. The module's redeployment trigger hashed only
  integration ids, which do not change when `uri`, `response_transfer_mode` or `timeout_milliseconds`
  change in place. It now hashes those attributes.
