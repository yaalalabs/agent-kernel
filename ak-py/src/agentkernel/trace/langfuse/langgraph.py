import logging
from typing import Any

from langchain_core.messages import HumanMessage
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from ...core import Session
from ...langgraph.langgraph import LangGraphRunner, LangGraphSessionConfigModel, LangGraphSessionConfigurable


class LangFuseLangGraph(LangGraphRunner):

    def __init__(self, client: Langfuse):
        """
        Initializes a LangFuseLangGraph instance.
        :param client: The Langfuse client instance.
        """
        super().__init__()
        self._client = client
        self._log = logging.getLogger("ak.trace.langfuse.langgraph")
        self._callback_handler = CallbackHandler()

    async def run(self, agent: Any, session: Session, prompt: Any):
        """
        Runs the LangGraph agent with the provided session and prompt.
        :param agent: The LangGraph agent to run.
        :param session: The session to run the agent in.
        :param prompt: The input prompt for the agent.
        :return: The response from the agent.
        """
        session_config = LangGraphSessionConfigModel(configurable=LangGraphSessionConfigurable(thread_id=session.id))
        config = session_config.model_dump()
        config["callbacks"] = [self._callback_handler]
        agent.agent.checkpointer = self._session(session).checkpointer
        result = await agent.agent.ainvoke(
            input={"messages": [HumanMessage(content=prompt)]},
            config=config,
        )
        last_message = result["messages"][-1]
        return last_message.content
