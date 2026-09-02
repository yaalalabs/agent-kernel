"""The sandbox worker process: consumes the sandbox queues and drives the kubernetes provider.

This is the entry point behind the chart's sandbox-worker Deployment (#503). It hosts the two
consumer loops (the request loop executes in sandbox pods; the output loop persists
completion records to the response store) plus the idle-session sweep. No agents and no REST
here: the agent side submits from the runner pods through the 'queue' broker flavor, waits a
bounded time, and recovers late results with check_sandbox_task.
"""

from agentkernel.sandbox import QueueBrokerWorker


def main():
    QueueBrokerWorker.run()


if __name__ == "__main__":
    main()
