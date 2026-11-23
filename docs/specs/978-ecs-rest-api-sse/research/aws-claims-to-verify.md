# AWS behaviours this design depends on

This design rests on four claims about AWS and the Terraform provider that were taken from the issue
and from AWS announcements. None of them could be verified by reading this repository.

**One has since been confirmed. Three are tested on the first real deployment**, before time goes into
the rest of the acceptance criteria — they are the claims that decide whether the change is possible
at all.

| # | Claim | How it is checked | If it fails |
| --- | --- | --- | --- |
| 1 | AWS provider `6.70.0` exposes `response_transfer_mode` and `integration_target` | provider schema, locally | **Confirmed — see below** |
| 2 | A REST API integrates directly with an ALB over VPC link V2, no NLB | the stack applies and serves one request end to end | The feature is not yet possible on AWS; the issue closes |
| 3 | With `responseTransferMode = "STREAM"`, SSE chunks arrive **incrementally** | `curl -N`, timestamping each chunk | The feature is not yet possible on AWS; the issue closes |
| 4 | The REST API's real idle timeout on a Regional endpoint | a route that stays silent, then emits | The ALB `idle_timeout` constant follows the measurement, not the documented 5 min |

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
this change's control. Every remaining risk is "AWS cannot do this yet", which no amount of Terraform
would fix.

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
3. **Claim 4:** drive a request whose agent stays silent for a measured interval before replying, and
   bisect the point at which the connection drops.

### Controls worth keeping

- Regional endpoint only. An edge-optimized endpoint reportedly keeps a 30 s streaming idle cap and
  would produce a false negative.
- The ALB `idle_timeout` must already be raised. At the default 60 s the ALB, not the gateway, is what
  cuts a long stream, and claim 4 would measure the wrong component.
- Record the AWS region. Feature availability in late 2025 may not be uniform.

## Results

| # | Result | Evidence |
| --- | --- | --- |
| 1 | **Confirmed** | provider schema, above |
| 2 | — | — |
| 3 | — | — |
| 4 | — | — |

Record claims 2 to 4 here once the first deployment has been tested, along with anything that should
change in `design.md` — in particular the ALB `idle_timeout` constant if claim 4 contradicts the
documented 5 minutes.
