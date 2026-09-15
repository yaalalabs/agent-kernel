"""Customising the Messenger integration by subclassing its inbound adapter.

An adapter is a translation function, so a customisation is an override of `_to_request`: you
answer the events you want to handle yourself and return None, and hand everything else to the
built-in normalisation. Nothing here runs the agent — that happens on the far side of the queue.
"""

import logging
from typing import Optional

from agentkernel.integration.adapter import WebhookRESTRequestHandler
from agentkernel.integration.adapter.base import InboundRequest
from agentkernel.messenger import MessengerInboundAdapter
from agentkernel.openai import OpenAIModule
from agentkernel.pipeline import IOHandler
from agents import Agent as OpenAIAgent

logger = logging.getLogger(__name__)

COMMANDS = {
    "/help": """Available Commands:

/help - Show this help message
/start - Start a new conversation

Just send a message to chat with the AI assistant! 💬""",
    "/start": """👋 Welcome! I'm your AI assistant.

Send me any question and I'll do my best to help you.
Type /help to see available commands.""",
}

SHORTHAND = {
    "u": "you",
    "r": "are",
    "ur": "your",
    "pls": "please",
    "thx": "thanks",
    "ty": "thank you",
    "btw": "by the way",
    "idk": "I don't know",
}


class CustomMessengerInboundAdapter(MessengerInboundAdapter):
    """Messenger adapter with command handling and message preprocessing."""

    async def _to_request(self, event: dict) -> Optional[InboundRequest]:
        sender_id = event.get("sender", {}).get("id")
        text = (event.get("message", {}).get("text") or "").strip()

        # Commands are answered here and never reach the agent.
        if text.startswith("/"):
            command = text.lower().split()[0]
            await self._api.sender_action(sender_id, "typing_on")
            await self._api.send_message(
                sender_id, [COMMANDS.get(command, f"Unknown command: {command}\nType /help for available commands.")]
            )
            await self._api.sender_action(sender_id, "typing_off")
            return None

        if text:
            event = {**event, "message": {**event["message"], "text": self._expand_shorthand(text)}}

        return await super()._to_request(event)

    @staticmethod
    def _expand_shorthand(text: str) -> str:
        return " ".join(SHORTHAND.get(word.lower(), word) if len(word) <= 3 else word for word in text.split())


general_agent = OpenAIAgent(
    name="general",
    handoff_description="General purpose assistant",
    instructions="""You are a helpful assistant communicating via Facebook Messenger.
    - Keep responses concise and formatted for mobile
    - Use emojis appropriately to make messages friendly
    - Break long responses into shorter paragraphs
    - Be conversational and friendly""",
)

OpenAIModule([general_agent])


if __name__ == "__main__":
    IOHandler.run(handlers=[WebhookRESTRequestHandler(CustomMessengerInboundAdapter())])
