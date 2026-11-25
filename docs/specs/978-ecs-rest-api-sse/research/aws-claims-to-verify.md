# AWS behaviours this design depends on

This design rests on five claims about AWS and the Terraform provider that were taken from the issue
and from AWS announcements. None of them could be verified by reading this repository.

**Two have since been confirmed. Three are tested on the first real deployment**, before time goes
into the rest of the acceptance criteria — they are the claims that decide whether the change is
possible at all.

| # | Claim | How it is checked | If it fails |
| --- | --- | --- | --- |
| 1 | AWS provider `6.70.0` exposes `response_transfer_mode` and `integration_target` | provider schema, locally | **Confirmed — see below** |
| 2 | A REST API integrates directly with an ALB over VPC link V2, no NLB | the stack applies and serves one request end to end | Diagnose first (below). The issue closes only on a confirmed AWS limitation |
| 3 | With `responseTransferMode = "STREAM"`, SSE chunks arrive **incrementally** | `curl -N`, timestamping each chunk | Diagnose first (below). The issue closes only on a confirmed AWS limitation |
| 4 | The REST API's real limits on a Regional endpoint: the **idle** timeout, and the **total** stream duration `timeoutInMillis` permits under `STREAM` | a route that stays silent then emits; and a route that emits steadily past 5 and 15 minutes | The `alb_idle_timeout` and integration-timeout **defaults** follow the measurements, not the documentation, which contradicts itself (5 min vs 15 min) |
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

Those last two contradict each other and both are current AWS documentation. What is certain is that
this is a **different cap from the ALB's**, and the design accounts for only one of them:

| Cap | Limits | Set by |
| --- | --- | --- |
| ALB `idle_timeout` | a **silent gap** between bytes | `alb_idle_timeout`, default 300 s |
| Integration `timeoutInMillis` | **total** integration duration | not set today — defaults to 29 s |

A stream that emits a chunk every two seconds for ten minutes never trips the ALB's idle timeout and
is killed by the integration timeout. This is folded into claim 4 below.

## 2–4. What to test on the first deployment

Test these before working through the rest of the acceptance criteria.

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
| 2 | — | — |
| 3 | — | — |
| 4 | — | — |
| 5 | **Confirmed** | OpenAPI extension reference, above |

Record claims 2 to 4 here once the first deployment has been tested, along with anything that should
change in `design.md` — in particular the `alb_idle_timeout` and `gateway_integration_timeout`
defaults, which claim 4a and 4b set between them. The documentation cannot: it gives 5 minutes and 15
minutes for the same cap.
