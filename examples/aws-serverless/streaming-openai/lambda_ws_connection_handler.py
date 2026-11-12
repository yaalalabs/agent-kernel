"""WebSocket connection handler Lambda: the `$connect` and `$disconnect` routes.

There is no code to write. `$connect` authenticates the `?token=` query parameter through the
identity provider named in config.yaml (the static provider here, its one credential resolved from
the DEMO_AUTH_TOKEN environment variable that deploy/main.tf passes in) and keys the connection by
the principal's subject, storing the whole principal for the frames that follow. A missing or refused
token closes the connection before it opens.
"""

from agentkernel.aws import WebsocketConnectionHandler

handler = WebsocketConnectionHandler.handler
