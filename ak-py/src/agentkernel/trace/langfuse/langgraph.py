import logging
from typing import Any

from langchain_core.messages import HumanMessage
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from ...core import Session
from ...core.model import AgentReply, AgentReplyText, AgentRequest, AgentRequestAny, AgentRequestText
from ...framework.langgraph.langgraph import LangGraphRunner, LangGraphSessionConfigModel, LangGraphSessionConfigurable


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

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the LangGraph agent with provided multi modal inputs.
        :param agent: The LangGraph agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        prompt = ""
        for req in requests:
            if isinstance(req, AgentRequestAny):  # AgentRequestAny is handled only by pre-hooks, not by the agent itself
                continue
            if isinstance(req, AgentRequestText):
                prompt = prompt + "\n" + req.text if prompt else req.text
            else:
                return AgentReplyText(
                    text="Sorry. Agent kernel LangGraph runner is unable to handle content other than text at the moment",
                    prompt=prompt,
                )

        if prompt.strip() == "":
            return AgentReplyText(text="Sorry. No valid text prompt found in the requests")

        with self._client.start_as_current_span(name="Agent Kernel LangGraph") as span:
            session_config = LangGraphSessionConfigModel(configurable=LangGraphSessionConfigurable(thread_id=session.id))
            config = session_config.model_dump()
            config["callbacks"] = [self._callback_handler]
            agent.agent.checkpointer = self._session(session).checkpointer
            result = await agent.agent.ainvoke(
                input={"messages": [HumanMessage(content=prompt)]},
                config=config,
            )
            last_message = result["messages"][-1]
            span.update_trace(session_id=session.id, input=prompt, output=last_message.content, tags=["agentkernel"])

        return AgentReplyText(text=last_message.content, prompt=prompt)
