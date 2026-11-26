# AWS behaviours this design depends on

This design rests on five claims about AWS and the Terraform provider that were taken from the issue
and from AWS announcements. None of them could be verified by reading this repository.

**Four are now confirmed. Claim 4 is deliberately deferred**: it sets two timeout defaults rather
than deciding whether the change is possible, so it is measured when someone needs the real
ceilings. Claims 2 and 3 — the two that decided whether this was possible at all — were confirmed on
a real deployment on 2026-11-26.

| # | Claim | How it is checked | If it fails |
| --- | --- | --- | --- |
| 1 | AWS provider `6.70.0` exposes `response_transfer_mode` and `integration_target` | provider schema, locally | **Confirmed — see below** |
| 2 | A REST API integrates directly with an ALB over VPC link V2, no NLB | the stack applies and serves one request end to end | **Confirmed — see below** |
| 3 | With `responseTransferMode = "STREAM"`, SSE chunks arrive **incrementally** | `curl -N`, timestamping each chunk | **Confirmed — see below** |
| 4 | The REST API's real limits on a Regional endpoint: the **idle** timeout, and the **total** stream duration `timeoutInMillis` permits under `STREAM` | a route that stays silent then emits; and a route that emits steadily past 5 and 15 minutes | The integration-timeout **default** follows the measurement. The idle limit is documented unambiguously (5 min, Regional) and `alb_idle_timeout = 300` follows it |
| 5 | `x-amazon-apigateway-integration` accepts `responseTransferMode` **and** `integrationTarget` | the OpenAPI extension reference, which enumerates every supported key | **Confirmed — see below** |

## 1. Provider support — confirmed 2026-11-23

Both fields exist on `aws_api_gateway_integration` in AWS provider `6.70.0`, the version pinned in
`ak-deployment/ak-aws/containerized/.terraform.lock.hcl`:

```
response_transfer_mode   string, optional
integration_target       string, optional
```

Method: `terraform init` in a throwaway directory pinning `hashicorp/aws 6.70.0`, then
`terraform providers schema -json`. No AWS credentials and no deployed infrastructure — the schema is
read out of the provider binary. Terraform 1.15.8, darwin_arm64.

Also confirmed present in the same schema: `aws_api_gateway_rest_api.body` and `put_rest_api_mode`,
`aws_api_gateway_deployment.triggers`, `aws_lb.idle_timeout` (number, optional), and both
`aws_apigatewayv2_vpc_link` and `aws_api_gateway_vpc_link`.

The schema carries no descriptions for these attributes, so the **allowed values** of
`response_transfer_mode` are not confirmed here — only that the argument is accepted. `"STREAM"` comes
from the AWS documentation; claim 3 settles it.

**Why this one mattered most:** a missing field would have needed a provider bump, which is outside
this change's control.

**What it does not cover:** these are arguments on `aws_api_gateway_integration`, and decision 6 does
not use that resource — it builds the API from an OpenAPI `body`, where the equivalents are vendor
extension keys inside `x-amazon-apigateway-integration`. Different surface, separate documentation.
That gap is claim 5.

## 5. The OpenAPI extension keys — confirmed 2026-11-25

Claim 1 confirmed `response_transfer_mode` and `integration_target` as **arguments on
`aws_api_gateway_integration`**. Decision 6 does not use that resource, so the question was whether the
same two settings exist as **extension keys** inside `x-amazon-apigateway-integration`, which is a
separate surface with its own documentation.

Both are in the OpenAPI extension reference
([api-gateway-swagger-extensions-integration](https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-swagger-extensions-integration.html)),
which enumerates every supported key — quoted verbatim:

| Extension key | What the reference says |
| --- | --- |
| `integrationTarget` | "The ALB or NLB ARN to send the request to. **Supported only for private integrations that use VPC links V2.**" |
| `responseTransferMode` | "Use `BUFFERED` to have API Gateway wait to receive the complete response before beginning transmission. Use `STREAM` to have API Gateway send partial responses back to the client as they become available." |

The same reference lists `http_proxy` as a valid `type`, and `connectionType` / `connectionId` as
supported keys.

**Method:** fetched the reference page and read the property table. No AWS credentials, no apply, no
deployed infrastructure. The throwaway apply this claim originally called for is unnecessary.

**This confirms more than the key names.** `integrationTarget`'s own description — "the ALB or NLB
ARN", "only for private integrations that use VPC links V2" — is claim 2's mechanism stated as
documentation. Claim 2 is still listed as deployment-tested because a documented capability is not a
working one, but its *shape* is no longer in question: an ALB ARN as the target of a V2 link is the
documented arrangement, not a hopeful reading.

AWS's own worked example on
[response-streaming-http](https://docs.aws.amazon.com/apigateway/latest/developerguide/response-streaming-http.html)
is an OpenAPI 3.0.1 document imported with `import-rest-api --parameters
endpointConfigurationTypes=REGIONAL`, which is the exact shape decision 6 builds:

```yaml
paths:
  /streaming:
    get:
      x-amazon-apigateway-integration:
        httpMethod: "GET"
        uri: "https://example.com"
        type: "http_proxy"
        timeoutInMillis: 900000
        responseTransferMode: "STREAM"
```

### Discovered here: the integration timeout is a second, separate cap

`timeoutInMillis` was absent from `design.md` until this finding, and leaving it unset is not safe:

- The extension reference states the ordinary range as "**Integration timeouts between 50 ms and
  29,000 ms**". An unset `timeoutInMillis` takes the 29 s default, which would cap every SSE stream at
  29 seconds and silently defeat the change.
- The streaming page says "When you use response streaming, you can configure the integration timeout
  up to **15 minutes**", and its example sets `timeoutInMillis: 900000` — 15 minutes.
- The *same page*, describing a `BUFFERED` → `STREAM` switch, says "If you customized the integration
  timeout, this timeout value is removed, as API Gateway streams your response for up to **5
  minutes**."

**Correction, 2026-11-26.** The survey above missed a sentence that resolves most of this. The same
page states the idle limit separately and unambiguously: "Your streams are subject to idle timeouts.
For Regional or private endpoints, the timeout is **5 minutes**. For edge-optimized endpoints, the
timeout is 30 seconds." So the page documents **two different limits**, not one figure twice:
5 minutes of silence, and 15 minutes of total duration. Reading the 5-minute figure as a total was
wrong, and so was the conclusion that the documentation contradicts itself about the total.

What does still conflict is narrower: the `BUFFERED` → `STREAM` note calls a customised timeout
"removed", while the configuration section says it can be set "up to 15 minutes". Whether
`timeoutInMillis` is honoured at all under `STREAM` is therefore still open — that is claim 4b.

Either way this is a **different cap from the ALB's**, and the design accounts for only one of them:

| Cap | Limits | Set by |
| --- | --- | --- |
| ALB `idle_timeout` | a **silent gap** between bytes | `alb_idle_timeout`, default 300 s |
| Integration `timeoutInMillis` | **total** integration duration | not set today — defaults to 29 s |

A stream that emits a chunk every two seconds for ten minutes never trips the ALB's idle timeout and
is killed by the integration timeout. This is folded into claim 4 below.

## 2–4. What to test on the first deployment

**Claims 2 and 3 were run on 2026-11-26 and passed** — results below. This section is kept as the
method, for repeating the measurements or for claim 4, which is still unmeasured.

1. Deploy an ECS example whose framework supports token streaming, configured
   `execution.mode: rest_sync` and `execution.message_type: delta`, with a **Redis or Valkey**
   response store. DynamoDB cannot stream chunks and would fail for an unrelated reason, hiding the
   result.
2. **Claim 3:** `curl -N -X POST <invoke_url>/api/v1/chat -d '…'` and timestamp the arrivals. Chunks
   spread over several seconds is a pass; one burst at the end is a fail, and is the current HTTP API
   behaviour. Run the same request against the old stack for comparison, so "it streamed" is not
   confused with "the reply was short enough to look instant".
3. **Claim 4a — the idle limit:** drive a request whose agent stays silent for a measured interval
   before replying, and bisect the point at which the connection drops.
4. **Claim 4b — the total limit:** drive a request that emits a chunk every two seconds and keeps
   going, with `timeoutInMillis` set to 900000, and record how long the stream survives. 5 minutes
   means the documentation's "removed, streams for up to 5 minutes" wins and `timeoutInMillis` is
   inert under `STREAM`; 15 minutes means the configured value is honoured. Re-run with
   `timeoutInMillis` at 120000 to see whether a *lower* value is honoured — if it is, the key matters
   and must be set deliberately rather than left to the 29 s default.

### A failure is not a verdict

Claims 2 and 3 close the issue only on a **confirmed AWS limitation**, never on a first red result.

- A failed apply is more often IAM, a security group, a subnet or a wrong ARN than a missing AWS
  feature. Read the API error, fix what it names, and retry before concluding anything.
- A response that arrives in one burst may be buffered by the client, by the agent (a framework that
  yields nothing until it finishes), or by a proxy in between — not by the gateway. `curl -N` against
  the ALB **directly**, bypassing the gateway, separates these: if that burst too, the gateway is not
  the component under test.
- Only a reproduction that isolates the gateway, with everything else ruled out, is grounds for
  closing.

### Controls worth keeping

- Regional endpoint only. An edge-optimized endpoint reportedly keeps a 30 s streaming idle cap and
  would produce a false negative.
- Set `alb_idle_timeout` **above the longest probe** for this run, not to its 300 s default.
  At the implicit 60 s the ALB cuts first; at exactly 300 s it still cuts first whenever the gateway
  allows more, and the run would report the ALB's limit as the gateway's. Set it to 900 s for the
  measurement, and confirm which component closed the connection — ALB access logs, or the shape of
  the error the client sees — before attributing the number to the gateway.
- Record the AWS region. Feature availability in late 2025 may not be uniform.

## Results

| # | Result | Evidence |
| --- | --- | --- |
| 1 | **Confirmed** | provider schema, above |
| 2 | **Confirmed** 2026-11-26 | the stack applies and serves; see below |
| 3 | **Confirmed** 2026-11-26 | 162 incremental frames over 3.78 s; see below |
| 4 | Deferred | not measured — both timeout defaults remain provisional |
| 5 | **Confirmed** | OpenAPI extension reference, above |

## 2 and 3. The first real deployment — confirmed 2026-11-26

Verified twice over, in CI and by hand, against
`examples/aws-containerized/openai-sse-queue-mode` (added by this change) in `us-east-2`.

**Claim 2 — the REST API reaches the ALB over VPC link V2, with no NLB.** The stack applies and serves.
The WebSocket example's state confirms the arrangement from the other side: in a WebSocket mode only
`aws_api_gateway_vpc_link.ws[0]` exists, so the V2 link really is absent there and the REST path is
the only consumer of it.

**Claim 3 — `responseTransferMode: "STREAM"` delivers chunks incrementally.**

| Measured | Value |
| --- | --- |
| Frames | 162 |
| First frame | +2.20 s |
| Span, first to last | 3.78 s |
| Reply length | 963 characters |

Roughly 25 frames every half second, steadily. `content-type: text/event-stream` with
`x-amzn-remapped-server: uvicorn`, so the container answered through the proxy. The weekly
integration test asserts the same property independently (`3 passed`, including an assertion that
the span between first and last frame exceeds 0.5 s, which a buffered reply cannot satisfy).

**Two unrelated defects blocked this verification and will block anyone repeating it.** Neither is
caused by this change; both are filed:

- [#1015](https://github.com/yaalalabs/agent-kernel/issues/1015) — chunk fan-out sends no
  `MessageDeduplicationId` when the inbound message has none, so no chunk reaches the response store
  and SSE returns `Stream delivery failed`. Not reproducible on demand: CI passed on the same code
  and queue configuration minutes earlier.
- [#1016](https://github.com/yaalalabs/agent-kernel/issues/1016) — the chunk wait issues one `BLPOP`
  for the whole budget against a client with a short read deadline, so "no chunk yet" surfaces as a
  redis socket traceback at ~5 s instead of the designed `Stream timed out`. This is what made #1015
  look like a Redis connectivity problem.

A third, smaller trap: a local deployment on Apple Silicon cannot build these images at all, because
`ak-deployment/ak-aws/common/modules/ecr/main.tf:37` hardcodes `platform = "linux/amd64"` and the
classic Docker builder cannot cross-build. Deploy from an amd64 host or from CI.

## 4. Still to measure

Claim 4 was deliberately skipped: it tunes two defaults rather than deciding feasibility, and SSE
works without it. The two halves no longer stand in the same place, though.

**4a — the idle limit: documented, not measured.** AWS states it plainly for the endpoint type this
module uses: "for Regional or private endpoints, the timeout is 5 minutes". That is a hard gateway
limit an operator cannot raise, so **`alb_idle_timeout = 300` is settled rather than provisional**
— it matches the cap the gateway enforces anyway, and a higher value only reaches callers that hit
the ALB directly inside the VPC. Measuring it would confirm the documentation, not decide anything.

**4b — the total limit: still open.** The page says the integration timeout is configurable "up to
15 minutes" and sets `timeoutInMillis: 900000` in its own example, yet also says switching to
`STREAM` *removes* a customised timeout. So **`gateway_integration_timeout = 900` remains
provisional**: the open question is whether `timeoutInMillis` is honoured under `STREAM` at all, and
whether a *lower* value is honoured if it is. Record the measurement here when someone needs the real
ceiling, and correct the default and its description from it rather than from the documentation.
