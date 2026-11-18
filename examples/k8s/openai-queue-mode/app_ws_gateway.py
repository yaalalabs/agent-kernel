"""The WebSocket gateway process: owns client sockets and nothing else.

This is the entry point behind the chart's ws-gateway Deployment (async execution mode,
either message type). It authenticates each /ws handshake through the identity provider named in
config.yaml (the `identity` block; the static provider here, its one credential resolved from the
DEMO_AUTH_TOKEN environment variable the chart injects from a Secret), enqueues chat frames
directly to the transport, and receives reply pushes from the Response Handler on
/internal/push; agents run in app_agent_runner.py and REST stays on app_io_handler.py.
"""

from agentkernel.pipeline import WebSocketGateway


def main():
    WebSocketGateway.run()


if __name__ == "__main__":
    main()
