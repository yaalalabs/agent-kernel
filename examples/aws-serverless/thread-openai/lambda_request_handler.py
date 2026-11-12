"""Request-handler Lambda: the chat route with thread recording, plus the thread read routes.

LambdaThreadHost hosts the same ThreadRequestHandler an app passes to the pipeline's IOHandler.run.
Creating it is what turns threads on: it takes over the built-in chat route, which then requires an
authenticated caller (the principal the authorizer put on the event), records the user message under
it and marks the queued request; the agent-runner Lambda records the reply. The read routes are registered here and delegated to the host.

Building the host runs its checks on cold start: queue mode in rest_sync/rest_async, the sqs
transport, the API_BASE_PATH/API_VERSION/AGENT_ENDPOINT variables Terraform sets, and a shared thread
store. ThreadRequestHandler() itself requires the identity block in config.yaml, so this Lambda gets
the same credential variables as the authorizer (deploy/main.tf).
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
