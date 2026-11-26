"""Request-handler Lambda: the chat route, plus A2A and MCP.

LambdaProtocolHost runs the same FastAPI app the pipeline's IOHandler serves (the A2A routes per agent, and the MCP
mount) on the API Gateway events registered below. Each call is enqueued like a REST chat request, runs on the
agent-runner Lambda, and its reply is read back from the response store: this Lambda never runs a model.

Building the host runs its checks on cold start: a REST execution mode, the API_BASE_PATH, API_VERSION and
AGENT_ENDPOINT variables Terraform sets, stateless MCP, the sqs transport, a shared response store and a wait within API
Gateway's 29 s. A deployment that could not work fails its init instead of failing calls later. The public a2a.url and
mcp.url (see config.yaml) are not checked.

The agents are registered first: the host builds the A2A cards and the MCP tools from the agent registry when it is
constructed (the in-memory registry here, so this Lambda imports the agents and needs their dependencies and memory).
"""

from agentkernel.aws import Lambda, LambdaProtocolHost, ProtocolPaths
from agentkernel.openai import OpenAIModule

from lambda_agents import assistant

OpenAIModule([assistant])

protocol = LambdaProtocolHost()

# /a2a, /a2a/{proxy+}, /mcp and /mcp/{proxy+}, for GET, POST and DELETE: the resource templates the module's
# enable_a2a_server and enable_mcp_server flags create (see deploy/main.tf).
for path, method in ProtocolPaths.ROUTES:
    Lambda.register(path, method=method)(protocol.handle)

handler = Lambda.handler
