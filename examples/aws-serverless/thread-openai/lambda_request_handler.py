"""Request-handler Lambda: the chat route with thread recording, plus the thread read routes.

LambdaThreadHost hosts the same ThreadRequestHandler an app passes to the pipeline's IOHandler.run.
Creating it is what turns threads on: it takes over the built-in chat route, which then requires a
`user_id`, records the user message and marks the queued request; the agent-runner Lambda records
the reply. The read routes are registered here and delegated to the host.

Building the host runs its checks on cold start: queue mode in rest_sync/rest_async, the sqs
transport, the API_BASE_PATH/API_VERSION/AGENT_ENDPOINT variables Terraform sets, a shared thread
store, and a ThreadRequestHandler without an Authoriser (the API Gateway authorizer authorizes).
"""

from agentkernel.aws import Lambda, LambdaThreadHost
from agentkernel.thread import ThreadRequestHandler

threads = LambdaThreadHost(ThreadRequestHandler())


@Lambda.register("/threads", method="GET")
def list_threads(event, context):
    return threads.list_threads(event, context)


@Lambda.register("/threads/{session_id}", method="GET")
def get_thread(event, context):
    return threads.get_thread(event, context)


handler = Lambda.handler
