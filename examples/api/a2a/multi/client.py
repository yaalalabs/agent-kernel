from uuid import uuid4

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.helpers import get_message_text
from a2a.types import (
    Message,
    Part,
    Role,
    SendMessageRequest,
)

REQUEST_TIMEOUT_SECONDS = 30.0


class A2AHttpClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.card = None
        self.context_id = None

    async def init(self):
        self.context_id = uuid4().hex
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as httpx_client:
            resolver = A2ACardResolver(
                httpx_client=httpx_client,
                base_url=self.base_url,
            )
            try:
                self.card = await resolver.get_agent_card()
            except Exception as e:
                raise RuntimeError("Failed to fetch the public agent card. Cannot continue.") from e

    async def send(self, message: str):
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as httpx_client:
            # The factory calls the card's HTTP+JSON interface and sends the A2A-Version: 1.0 header.
            config = ClientConfig(streaming=False, httpx_client=httpx_client, supported_protocol_bindings=["HTTP+JSON"])
            client = ClientFactory(config).create(self.card)

            request = SendMessageRequest(
                message=Message(
                    role=Role.ROLE_USER,
                    message_id=uuid4().hex,
                    context_id=self.context_id,
                    parts=[Part(text=message)],
                )
            )

            return [get_message_text(item.message) async for item in client.send_message(request)][0]
