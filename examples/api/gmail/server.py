import asyncio
from agentkernel.gmail import AgentGmailRequestHandler
from agentkernel.openai import OpenAIModule
from agents import Agent as OpenAIAgent

# Create your agent
general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general email queries",
    instructions="""You are an AI email assistant. Your role is to:
- Read incoming emails carefully
- Provide helpful, professional responses
- Keep responses concise and clear
- Maintain a friendly and professional tone

When replying to emails:
1. Address the sender's questions or concerns
2. Provide relevant information
3. Keep it brief (2-3 paragraphs max)
4. Sign off professionally
""",
)

# Initialize module with agent
OpenAIModule([general_agent])


async def main():
    """Main function to run Gmail bot."""
    handler = AgentGmailRequestHandler()

    # Authenticate with Gmail
    handler.authenticate()

    print("Gmail bot started! Polling for new emails...")
    print("Press Ctrl+C to stop")

    try:
        # Start polling loop
        await handler.start_polling()
    except KeyboardInterrupt:
        print("\nStopping Gmail bot...")
        handler.stop_polling()


if __name__ == "__main__":
    asyncio.run(main())
