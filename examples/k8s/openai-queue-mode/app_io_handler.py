"""The io process: Request Handler (REST API) + Response Handler threads.

This is the entry point behind the chart's io-handler Deployment. It terminates REST, enqueues
requests to the input queue, consumes the output queue, and serves replies from the response
store; agents run in the other process (app_agent_runner.py), so no modules are registered
here.

For WebSocket execution modes (async/stream) the chart adds a separate gateway Deployment
running WebSocketGateway.run(auth_validator=...); the io handler's API stays plain REST.
"""

from agentkernel.pipeline import IOHandler


def main():
    IOHandler.run()


if __name__ == "__main__":
    main()
