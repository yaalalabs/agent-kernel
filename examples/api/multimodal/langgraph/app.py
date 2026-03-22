from agentkernel.api import RESTAPI
from agentkernel.langgraph import LangGraphModule, LangGraphToolBuilder
from langchain_openai import ChatOpenAI

from langgraph.prebuilt import create_react_agent

model = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)

general_agent = create_react_agent(
    name="general",
    model=model,
    tools=LangGraphToolBuilder.bind([]),
    prompt="You provide assistance with general queries. Give short and clear answers",
)

LangGraphModule([general_agent])

if __name__ == "__main__":
    RESTAPI.run()
