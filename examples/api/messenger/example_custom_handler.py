import logging

from agentkernel.api import RESTAPI
from agentkernel.fbmessenger import AgentFBMessengerRequestHandler
from agentkernel.openai import OpenAIModule
from agents import Agent as OpenAIAgent

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CustomMessengerHandler(AgentFBMessengerRequestHandler):
    """
    Custom Facebook Messenger handler with enhanced features:
    - Command support (/help, /start)
    - Message preprocessing
    - Custom error messages
    """

    async def _handle_message(self, messaging_event: dict):
        """
        Override to add custom message handling logic.
        """
        sender_id = messaging_event.get("sender", {}).get("id")
        message = messaging_event.get("message", {})
        message_text = message.get("text", "").strip()

        if not message_text:
            # Handle non-text messages
            if "attachments" in message:
                await self._send_message(
                    sender_id, "I received your attachment, but I can only process text messages at the moment."
                )
            return

        # Handle commands
        if message_text.startswith("/"):
            await self._handle_command(message_text, sender_id)
            return

        # Preprocess message
        processed_text = self._preprocess_message(message_text)

        # Create modified messaging event with processed text
        modified_event = messaging_event.copy()
        modified_event["message"] = message.copy()
        modified_event["message"]["text"] = processed_text

        # Call parent handler with processed message
        await super()._handle_message(modified_event)

    async def _handle_command(self, command: str, sender_id: str):
        """
        Handle special commands.
        """
        command = command.lower().split()[0]  # Get first word

        await self._send_typing_indicator(sender_id, True)

        if command == "/help":
            help_text = """Available Commands:

/help - Show this help message
/start - Start a new conversation

Just send a message to chat with the AI assistant! 💬"""
            await self._send_message(sender_id, help_text)

        elif command == "/start":
            welcome_text = """👋 Welcome! I'm your AI assistant.

Send me any question and I'll do my best to help you.
Type /help to see available commands."""
            await self._send_message(sender_id, welcome_text)

        else:
            await self._send_message(sender_id, f"Unknown command: {command}\nType /help for available commands.")

        await self._send_typing_indicator(sender_id, False)

    def _preprocess_message(self, text: str) -> str:
        """
        Preprocess message text before sending to agent.
        """
        # Convert common chat shorthand
        replacements = {
            "u": "you",
            "r": "are",
            "ur": "your",
            "pls": "please",
            "thx": "thanks",
            "ty": "thank you",
            "btw": "by the way",
            "idk": "I don't know",
        }

        words = text.split()
        processed_words = []

        for word in words:
            lower_word = word.lower()
            # Only replace if it's a standalone shorthand
            if lower_word in replacements and len(word) <= 3:
                processed_words.append(replacements[lower_word])
            else:
                processed_words.append(word)

        return " ".join(processed_words)


# Create agent
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
    handler = CustomMessengerHandler()
    RESTAPI.run([handler])
