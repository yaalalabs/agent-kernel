from uuid import uuid4

import httpx
from a2a.client import A2ACardResolver, ClientConfig
from a2a.client.base_client import BaseClient
from a2a.client.client import SendMessageRequest
from a2a.client.transports import RestTransport
from a2a.types import Message, Part, Role


class A2AHttpClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.card = None
        self.context_id = None

    async def init(self):
        self.context_id = uuid4().hex
        async with httpx.AsyncClient() as httpx_client:
            resolver = A2ACardResolver(
                httpx_client=httpx_client,
                base_url=self.base_url,
            )
            try:
                self.card = await resolver.get_agent_card()
            except Exception as e:
                raise RuntimeError("Failed to fetch the public agent card. Cannot continue.") from e

    async def send(self, message: str) -> str:
        async with httpx.AsyncClient() as httpx_client:
            config = ClientConfig(streaming=False)
            client = BaseClient(
                card=self.card,
                config=config,
                transport=RestTransport(httpx_client, self.card, url=self.base_url),
                interceptors=[],
            )

            msg = Message()
            msg.message_id = uuid4().hex
            msg.context_id = self.context_id
            msg.role = Role.ROLE_USER
            part = Part()
            part.text = message
            msg.parts.append(part)

            req = SendMessageRequest()
            req.message.CopyFrom(msg)

            events = [event async for event in client.send_message(req)]
            if not events:
                return ""

            # Non-streaming response: first event carries the reply as a Message or Task
            first = events[0]
            if first.HasField("message"):
                parts = first.message.parts
                return parts[0].text if parts else ""
            if first.HasField("task"):
                artifacts = first.task.artifacts
                if artifacts and artifacts[0].parts:
                    return artifacts[0].parts[0].text
            return ""
