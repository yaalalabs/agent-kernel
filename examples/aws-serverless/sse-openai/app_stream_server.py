"""Starts the request-handler Lambda's SSE server. The Lambda Web Adapter forwards every request to it.

No agent module is imported here: the request handler only enqueues the request and streams the chunks
back. The agent runs in the agent-runner Lambda.
"""

from agentkernel.aws import LambdaStreamServer

if __name__ == "__main__":
    LambdaStreamServer.run()
