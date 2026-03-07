from agentkernel.api import RESTAPI
from agentkernel.core.multimodal import analyze_attachments
from agentkernel.langgraph import LangGraphModule, LangGraphToolBuilder
from langchain_openai import ChatOpenAI

from langgraph.prebuilt import create_react_agent

model = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)

# LangGraph compiles a static graph at startup — tools cannot be injected
# after compile(). The analyze_attachments tool must be passed explicitly here

general_agent = create_react_agent(
    name="general",
    model=model,
    tools=LangGraphToolBuilder.bind([analyze_attachments]),
    prompt="You provide assistance with general queries. Give short and clear answers",
)

LangGraphModule([general_agent])

if __name__ == "__main__":
    RESTAPI.run()
