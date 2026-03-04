from agentkernel.api import RESTAPI
from agentkernel.langgraph import LangGraphModule
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

model = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)

support_agent = create_react_agent(
    name="support",
    tools=[],
    model=model,
    prompt="You are an AI assistant that can see and analyze images. "
           "When a user uploads an image, describe it in detail. "
           "Remember context from previous messages in the conversation.",
)

LangGraphModule([support_agent])

if __name__ == "__main__":
    RESTAPI.run()
