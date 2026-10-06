# Agent Kernel with AWS CloudWatch tracing

This package demonstrates Agent Kernel tracing agent execution to
[Amazon CloudWatch](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Transaction-Search.html)
over OpenTelemetry. The agents are the same OpenAI Agents SDK agents as [../openai](../openai) — tracing is
transparent, so the only difference is `config.yaml`, which sets:

```yaml
trace:
  enabled: true
  type: cloudwatch
```

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

## One-time AWS account setup

Spans are sent to the X-Ray OTLP endpoint (`https://xray.<region>.amazonaws.com/v1/traces`), which needs
**CloudWatch Transaction Search** enabled once per account and region
([AWS guide](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Enable-TransactionSearch.html)).
Enable it from the CloudWatch console (**Application Signals → Transaction Search → Enable Transaction
Search**), or with the AWS CLI:

    aws logs put-resource-policy --policy-name AgentKernelTransactionSearch --policy-document '{
      "Version": "2012-10-17",
      "Statement": [{
        "Sid": "TransactionSearchXRayAccess",
        "Effect": "Allow",
        "Principal": {"Service": "xray.amazonaws.com"},
        "Action": "logs:PutLogEvents",
        "Resource": [
          "arn:aws:logs:<region>:<account-id>:log-group:aws/spans:*",
          "arn:aws:logs:<region>:<account-id>:log-group:/aws/application-signals/data:*"
        ],
        "Condition": {
          "ArnLike": {"aws:SourceArn": "arn:aws:xray:<region>:<account-id>:*"},
          "StringEquals": {"aws:SourceAccount": "<account-id>"}
        }
      }]
    }'
    aws xray update-trace-segment-destination --destination CloudWatchLogs
    aws xray get-trace-segment-destination     # "Status": "ACTIVE" once ready; allow ~10 minutes

The identity running the demo needs permission to write traces — attach the AWS managed policy
`AWSXrayWriteOnlyAccess`.

## Run

Set your OpenAI API key, an AWS region, and AWS credentials (any source the AWS SDK reads — environment
variables, a profile, SSO, or an instance/task role), then run the demo:

    export OPENAI_API_KEY=sk-...
    export AWS_REGION=us-east-1
    export AWS_PROFILE=my-profile     # or AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
    python demo.py

Each agent run is a span named `Agent Kernel OpenAI` carrying the `session.id`, with the OpenAI Agents SDK's
agent, LLM, and tool spans nested under it. Find them in the CloudWatch console under
**Application Signals → Transaction Search** (filter on `session.id`), and under **GenAI Observability**.
The service is named `AgentKernel`; set `OTEL_SERVICE_NAME` to change it.

To export through a local collector or the CloudWatch agent instead of straight to X-Ray, point the
standard OpenTelemetry endpoint variable at it — no region or signing is needed then:

    export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:4318/v1/traces

To run tests (requires the AWS setup above):

    uv run pytest -s
