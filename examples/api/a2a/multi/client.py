from uuid import uuid4

import httpx
from a2a.client import A2ACardResolver, ClientConfig
from a2a.client.base_client import BaseClient
from a2a.client.transports import RestTransport
from a2a.types import (
    Message,
    Part,
    Role,
    TextPart,
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
            config = ClientConfig(streaming=False)
            client = BaseClient(
                card=self.card,
                config=config,
                transport=RestTransport(httpx_client, self.card),
                consumers=[],
                middleware=[],
            )

            first_message = Message(
                role=Role.user,
                message_id=uuid4().hex,
                context_id=self.context_id,
                parts=[Part(root=TextPart(text=message))],
            )

            return [event async for event in client.send_message(first_message)][0].parts[0].root.text
