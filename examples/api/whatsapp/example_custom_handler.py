import logging

from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agentkernel.whatsapp import AgentWhatsAppRequestHandler
from agents import Agent as OpenAIAgent

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CustomWhatsAppHandler(AgentWhatsAppRequestHandler):
    """
    Custom WhatsApp handler with enhanced features:
    - Command support (/help, /status)
    - Message preprocessing
    - Custom error messages
    """

    async def _handle_message(self, message: dict, value: dict):
        """
        Override to add custom message handling logic.
        """
        message_type = message.get("type")
        from_number = message.get("from")
        message_id = message.get("id")

        # Extract text
        text = None
        if message_type == "text":
            text = message.get("text", {}).get("body", "").strip()
        elif message_type == "interactive":
            interactive = message.get("interactive", {})
            if interactive.get("type") == "button_reply":
                text = interactive.get("button_reply", {}).get("title")
            elif interactive.get("type") == "list_reply":
                text = interactive.get("list_reply", {}).get("title")

        if not text:
            # Handle unsupported message types
            await self._send_message(
                from_number,
                "Sorry, I can only process text messages at the moment.",
                message_id,
            )
            return

        # Handle commands
        if text.startswith("/"):
            await self._handle_command(text, from_number, message_id)
            return

        # Preprocess message
        processed_text = self._preprocess_message(text)

        # Create a modified message dict with processed text
        modified_message = message.copy()
        if message_type == "text":
            modified_message["text"] = {"body": processed_text}

        # Call parent handler with processed message
        await super()._handle_message(modified_message, value)

    async def _handle_command(self, command: str, from_number: str, message_id: str):
        """
        Handle special commands.
        """
        command = command.lower().split()[0]  # Get first word

        if command == "/help":
            help_text = """*Available Commands:*

/help - Show this help message
/status - Check bot status
/start - Start a new conversation

Just send a message to chat with the AI assistant!"""
            await self._send_message(from_number, help_text, message_id)

        elif command == "/status":
            status_text = "✅ Bot is online and ready to help!"
            await self._send_message(from_number, status_text, message_id)

        elif command == "/start":
            welcome_text = """👋 Welcome! I'm your AI assistant.

Send me any question and I'll do my best to help you.
Type /help to see available commands."""
            await self._send_message(from_number, welcome_text, message_id)

        else:
            await self._send_message(
                from_number,
                f"Unknown command: {command}\nType /help for available commands.",
                message_id,
            )

    def _preprocess_message(self, text: str) -> str:
        """
        Preprocess message text before sending to agent.
        """
        # Convert common WhatsApp shorthand
        replacements = {
            "u": "you",
            "r": "are",
            "ur": "your",
            "pls": "please",
            "thx": "thanks",
            "ty": "thank you",
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
    instructions="""You are a helpful assistant communicating via WhatsApp.
    - Keep responses concise and formatted for mobile
    - Use emojis appropriately to make messages friendly
    - Break long responses into shorter paragraphs
    - Be conversational and friendly""",
)

OpenAIModule([general_agent])


if __name__ == "__main__":
    handler = CustomWhatsAppHandler()
    RESTAPI.run(handler=handler)
