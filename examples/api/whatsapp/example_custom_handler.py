"""Customising the WhatsApp integration by subclassing its inbound adapter.

An adapter is a translation function, so a customisation is an override of `_to_request`: you
answer the messages you want to handle yourself and return None, and hand everything else to the
built-in normalisation. Nothing here runs the agent — that happens on the far side of the queue.
"""

import logging
from typing import Optional

from agentkernel.integration.adapter import WebhookRESTRequestHandler
from agentkernel.integration.adapter.base import InboundRequest
from agentkernel.openai import OpenAIModule
from agentkernel.pipeline import IOHandler
from agentkernel.whatsapp import WhatsAppInboundAdapter
from agents import Agent as OpenAIAgent

logger = logging.getLogger(__name__)

COMMANDS = {
    "/help": """*Available Commands:*

/help - Show this help message
/status - Check bot status
/start - Start a new conversation

Just send a message to chat with the AI assistant!""",
    "/status": "✅ Bot is online and ready to help!",
    "/start": """👋 Welcome! I'm your AI assistant.

Send me any question and I'll do my best to help you.
Type /help to see available commands.""",
}

# Common WhatsApp shorthand, expanded before the agent sees the message.
SHORTHAND = {"u": "you", "r": "are", "ur": "your", "pls": "please", "thx": "thanks", "ty": "thank you"}


class CustomWhatsAppInboundAdapter(WhatsAppInboundAdapter):
    """WhatsApp adapter with command handling and message preprocessing."""

    async def _to_request(self, message: dict) -> Optional[InboundRequest]:
        text = self._text_of(message)

        # Commands are answered here and never reach the agent.
        if text and text.startswith("/"):
            command = text.lower().split()[0]
            reply = COMMANDS.get(command, f"Unknown command: {command}\nType /help for available commands.")
            await self._say(message.get("from"), reply, message.get("id"))
            return None

        if text:
            message = {**message, "text": {"body": self._expand_shorthand(text)}}

        return await super()._to_request(message)

    @staticmethod
    def _text_of(message: dict) -> str:
        if message.get("type") == "text":
            return (message.get("text", {}).get("body") or "").strip()
        return ""

    @staticmethod
    def _expand_shorthand(text: str) -> str:
        return " ".join(SHORTHAND.get(word.lower(), word) if len(word) <= 3 else word for word in text.split())


general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and clear answers suitable for WhatsApp messaging.",
)

OpenAIModule([general_agent])


if __name__ == "__main__":
    IOHandler.run(handlers=[WebhookRESTRequestHandler(CustomWhatsAppInboundAdapter())])
