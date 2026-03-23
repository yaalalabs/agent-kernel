import asyncio
import logging

from agentkernel.gmail import AgentGmailRequestHandler
from agentkernel.openai import OpenAIModule
from agents import Agent as OpenAIAgent

# Configure logging to show all messages in terminal
logging.basicConfig(
    level=logging.DEBUG,  # Show DEBUG and above (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# Create your agent
general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general email queries",
    instructions="""You are an AI email assistant. Your role is to:
- Read incoming emails carefully
- Analyze any attached images or documents
- Provide helpful, professional responses
- Keep responses concise and clear
- Maintain a friendly and professional tone

When replying to emails:
1. Extract sender's name from the "From:" field 
2. Start your response with "Hi [Name]," or "Hello [Name],"
3. Address the sender's questions or concerns
4. If images are attached, describe what you see and provide relevant analysis
5. If documents are attached, summarize key points and answer questions about them
6. Provide relevant information based on email content AND attachments
7. Keep it brief (2-3 paragraphs max)
8. Do NOT include "Subject:" in your response
9. Do NOT add signature or closing (handler will add automatically)
""",
)

# Initialize module with agent
OpenAIModule([general_agent])


async def main():

    handler = AgentGmailRequestHandler()

    # Authenticate with Gmail
    handler.authenticate()

    logging.info("Gmail bot started! Polling for new emails...")

    try:
        # Start polling loop
        await handler.start_polling()
    except KeyboardInterrupt:
        logging.info("Stopping Gmail bot...")
        handler.stop_polling()


if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            asyncio.set_event_loop(asyncio.new_event_loop())
            asyncio.run(main())
        else:
            loop.run_until_complete(main())

    except RuntimeError:
        asyncio.run(main())
