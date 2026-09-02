from agentkernel.gmail import GmailInboundAdapter
from agentkernel.integration.adapter import PollerRunner
from agentkernel.openai import OpenAIModule
from agentkernel.pipeline import IOHandler
from agents import Agent as OpenAIAgent

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


if __name__ == "__main__":
    adapter = GmailInboundAdapter()
    adapter.authenticate()
    IOHandler.run(pollers=[PollerRunner(adapter)])
