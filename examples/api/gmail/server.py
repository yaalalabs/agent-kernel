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
1. Extract sender's name from the "From:" field 
2. Start your response with "Hi [Name]," or "Hello [Name],"
3. Address the sender's questions or concerns
4. Provide relevant information
5. Keep it brief (2-3 paragraphs max)
6. Do NOT include "Subject:" in your response
7. Do NOT add signature or closing (handler will add automatically)
""",
)

# Initialize module with agent
OpenAIModule([general_agent])


async def main():

    handler = AgentGmailRequestHandler()

    # Authenticate with Gmail
    handler.authenticate()

    print("Gmail bot started! Polling for new emails...")

    try:
        # Start polling loop
        await handler.start_polling()
    except KeyboardInterrupt:
        print("\nStopping Gmail bot...")
        handler.stop_polling()


if __name__ == "__main__":
    asyncio.run(main())
