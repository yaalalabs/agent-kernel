"""The io process: Request Handler (REST API) + Response Handler threads.

This is the entry point behind the chart's io-handler Deployment. It terminates REST,
enqueues requests to the input queue, consumes the output queue, and serves replies from the
response store; agents run in app_agent_runner.py and sandbox executions in
app_sandbox_worker.py, so nothing is registered here.
"""

from agentkernel.pipeline import IOHandler


def main():
    IOHandler.run()


if __name__ == "__main__":
    main()
