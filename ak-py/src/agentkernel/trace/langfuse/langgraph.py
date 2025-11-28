import logging
from typing import Any

from langchain_core.messages import HumanMessage
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from agentkernel.core.model import AgentReply, AgentReplyText, AgentRequest, AgentRequestText

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
        with self._client.start_as_current_span(name="Agent Kernel LangGraph") as span:
            session_config = LangGraphSessionConfigModel(
                configurable=LangGraphSessionConfigurable(thread_id=session.id)
            )
            config = session_config.model_dump()
            config["callbacks"] = [self._callback_handler]
            agent.agent.checkpointer = self._session(session).checkpointer
            result = await agent.agent.ainvoke(
                input={"messages": [HumanMessage(content=prompt)]},
                config=config,
            )
            last_message = result["messages"][-1]
            output = last_message.content
            span.update_trace(session_id=session.id, input=prompt, output=output, tags=["agentkernel"])
        return output

    async def run_multi(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the LangGraph agent with provided multi modal inputs.
        :param agent: The LangGraph agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        reply = "No valid requests found"
        for req in requests:
            if isinstance(req, AgentRequestText):
                reply = await self.run(agent, session, req.text)
                break
            else:
                reply = "Sorry. Agent kernel LangGraph runner is unable to handle content other than text at the moment"
            break

        if hasattr(reply, "raw"):
            reply = str(reply.raw)
        else:
            reply = str(reply)

        return AgentReplyText(text=reply)
