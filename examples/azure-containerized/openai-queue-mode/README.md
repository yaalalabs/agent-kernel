# Open Agent Kernel queue mode on Azure Container Apps with Service Bus

This demo runs OpenAI Agents SDK agents in Open Agent Kernel's two-process queue pipeline on Azure. An edge
Container App takes REST calls behind API Management and puts each request on an Azure Service Bus queue.
A second Container App, the agent runner, takes requests off that queue, runs the agent, and sends the
reply back on an output queue. Agent runner replicas are added as the input queue grows.

```
client -> APIM -> edge app (app_io_handler.py) -> Service Bus "input" -> agent runner app (app_agent_runner.py)
                     ^                                                         |
                     +------ Redis response store <- edge <- Service Bus "output" <-+
```

## Deployed Resources

The `ak-containerized/azurerm` module with `queue_mode = true` deploys:

- **Edge Container App**: REST (`IOHandler.run()`), the image's default command
- **Agent runner Container App**: `AgentRunner.run()` in the same image, no ingress, scaled by a KEDA
  `azure-servicebus` rule on the input queue
- **Azure Service Bus** (Standard): namespace `<prefix>-queues` with session-enabled `input` and `output`
  queues. Both apps sign in with their managed identity; key-based access is off.
- **Azure Managed Redis**: sessions, and the response store the edge reads replies from
- **API Management, Container Registry, Log Analytics, Application Insights, Virtual Network**: as in the
  other Azure containerized examples

`deploy/main.tf` also gives whoever runs the deploy the **Azure Service Bus Data Owner** role on the
namespace. Only `servicebus_contract_test.py` needs it; drop that resource if you don't run that test.

## Files

| File | What it is |
|---|---|
| `app_agents.py` | The triage, math and history agents, shared by both apps |
| `app_io_handler.py` | Edge entry point |
| `app_agent_runner.py` | Agent runner entry point (the module's `agent_runner_command`) |
| `config.yaml` | Transport (`servicebus`), response store and session store types; the module injects the addresses |
| `app_test.py` | Two `rest_sync` turns on one session through APIM |
| `servicebus_contract_test.py` | OAK's queue transport contract against the deployed namespace |

## Prerequisites

- Azure CLI logged in (`az login`) to a subscription where you can create these resources and role assignments
- Terraform `1.9.5` or higher, Docker, and [uv](https://docs.astral.sh/uv/)
- An existing resource group

## Deploy

1. Set `resource_group_name`, `prefix` and `publisher_email` in `deploy/terraform.tfvars`.
2. Export your OpenAI key for Terraform: `export TF_VAR_openai_api_key=sk-...`
3. Build and deploy:

```bash
./build.sh
(cd deploy && ./deploy.sh)
```

## Test

```bash
export AK_TEST_ENDPOINT=$(cd deploy && terraform output -raw agent_invoke_url)
export AK_TEST_SERVICEBUS_NAMESPACE=$(cd deploy && terraform output -raw servicebus_namespace)
uv run pytest
```

Without `AK_TEST_SERVICEBUS_NAMESPACE` the contract test is skipped. With it, each test creates its own pair
of short-lived queues in the namespace; they delete themselves after 5 idle minutes.

Call the agent directly:

```bash
curl -X POST "$AK_TEST_ENDPOINT" -H "Content-Type: application/json" \
  -d '{"prompt": "Who won the 1996 cricket world cup?", "session_id": "s1", "agent": "triage"}'
```

## Notes

- `execution.mode` is set per deployment. This example uses `rest_sync`. `rest_async` also works over the
  same queues, but polling needs a `GET` route added through the module's `gateway_endpoints`.
- WebSocket replies are not supported in Azure queue mode.
- The module pins `max_receive_count` to 3 through environment variables, one below the queues' max delivery
  count, so a value in `config.yaml` is ignored.

## Clean up

```bash
(cd deploy && terraform destroy)
```
