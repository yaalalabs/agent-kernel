from __future__ import annotations

from typing import Any, List

from agents import Agent, Runner
from agents.memory.session import SessionABC

from agentkernel.core.model import (
    AgentReply,
    AgentReplyText,
    AgentRequest,
    AgentRequestAny,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
)

from ... import PostHook, PreHook
from ...core import Agent as BaseAgent
from ...core import Module
from ...core import Runner as BaseRunner
from ...core import Session
from ...core.config import AKConfig
from ...trace import Trace

FRAMEWORK = "openai"


class OpenAISession(SessionABC):
    """
    OpenAISession class provides a session for OpenAI Agents SDK-based agents.
    """

    def __init__(self):
        """
        Initializes an OpenAISession instance.
        """
        self._items = []

    async def get_items(self, limit: int | None = None) -> List[dict]:
        """
        Retrieve items stored in this session.
        :param limit: Optional limit on the number of items to retrieve.
        :return: List of items in the session.
        """
        if limit is not None:
            return self._items[:limit]
        return self._items

    async def add_items(self, items: List[dict]) -> None:
        """
        Add items to this session.
        :param items: List of items to add.
        """
        self._items.extend(items)

    async def pop_item(self) -> dict | None:
        """
        Remove and return the most recent item from this session.
        :return: The most recent item, or None if the session is empty.
        """
        if self._items:
            return self._items.pop()
        return None

    async def clear_session(self) -> None:
        """
        Clear all items for this session.
        """
        self._items.clear()


class OpenAIRunner(BaseRunner):
    """
    OpenAIRunner class provides a runner for OpenAI Agents SDK based agents.
    """

    def __init__(self):
        """
        Initializes an OpenAIRunner instance.
        """
        super().__init__(FRAMEWORK)

    @staticmethod
    def _session(session: Session) -> OpenAISession | None:
        """
        Returns the OpenAI session associated with the provided session.
        :param session: The session to retrieve the OpenAI session for.
        :return: OpenAISession instance.
        """
        if session is None:
            return None
        return session.get(FRAMEWORK) or session.set(FRAMEWORK, OpenAISession())

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the OpenAI agent with provided multi modal inputs.
        :param agent: The OpenAI agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        prompt = ""
        message_content = []
        try:
            for req in requests:
                if isinstance(req, AgentRequestAny):  # AgentRequestAny is handled only by pre-hooks, not by the agent itself
                    continue

                if isinstance(req, AgentRequestText):
                    text = req.text
                    prompt = prompt + "\n" + text if prompt else text
                    message_content.append({"role": "user", "content": text})

                elif isinstance(req, AgentRequestImage):
                    # Handle image requests - OpenAI expects base64 or URL format
                    if not req.image_data:
                        raise ValueError("no image input provided")

                    image_url = req.image_data
                    # If it's base64 and doesn't have the data URI prefix, add it
                    if not image_url.startswith(("http://", "https://", "s3://", "data:")):
                        if not req.mime_type:
                            raise ValueError("mime_type is missing for image input, either in the base64 or explicitly")
                        mime_type = req.mime_type
                        image_url = f"data:{mime_type};base64,{image_url}"

                    message_content.append({"role": "user", "content": [{"type": "input_image", "detail": "auto", "image_url": image_url}]})

                elif isinstance(req, AgentRequestFile):
                    # Handle file attachments - OpenAI expects base64 or URL format
                    if not req.file_data:
                        raise ValueError("no file input provided")

                    file_url = req.file_data
                    # If it's a remote URL, use it directly
                    if file_url.startswith(("http://", "https://", "s3://")):
                        message_content.append({"role": "user", "content": [{"type": "input_file", "file_url": file_url}]})
                    else:
                        mime_type = req.mime_type
                        # If it's base64 and doesn't have the data URI prefix, add it
                        if not file_url.startswith(("data:")):
                            if not req.mime_type:
                                raise ValueError("mime_type is missing for file input, either in the base64 or explicitly")
                            file_url = f"data:{mime_type};base64,{file_url}"

                        message_content.append(
                            {
                                "role": "user",
                                "content": [{"type": "input_file", "filename": req.name, "file_data": file_url}],
                            }
                        )

            if not message_content:
                return AgentReplyText(text="Sorry. No valid content found in the requests")

            # Use the structured message format if we have images or files, otherwise use simple prompt
            if len(message_content) == 1 and isinstance(message_content[0].get("content"), str):
                # Simple text-only case
                reply = (await Runner.run(agent.agent, prompt, session=self._session(session))).final_output
            else:
                # Multimodal case with images/files. When using multimodal inputs, OpenAI cannot handle session. So these inputs are not saved in the context
                reply = (await Runner.run(agent.agent, message_content, session=None)).final_output

            return AgentReplyText(text=str(reply), prompt=prompt)
        except Exception as e:
            return AgentReplyText(text=f"Error during agent execution: {str(e)}")


class OpenAIAgent(BaseAgent):
    """
    OpenAIAgent class provides an agent wrapping for OpenAI Agent SDK-based agents.
    """

    def __init__(self, name: str, runner: OpenAIRunner, agent: Agent):
        """
        Initializes an OpenAIAgent instance.
        :param name: Name of the agent.
        :param runner: Runner associated with the agent.
        :param agent: The OpenAI agent instance.
        """
        super().__init__(name, runner)
        self._agent = agent

    @property
    def agent(self) -> Agent:
        """
        Returns the OpenAI agent instance.
        """
        return self._agent

    def get_description(self):
        """
        Returns the description of the agent.
        """
        return self.agent.instructions

    def get_a2a_card(self):
        """
        Returns the A2A AgentCard associated with the agent.
        """
        from a2a.types import AgentSkill

        skills = []
        for tool in self.agent.tools:
            skills.append(AgentSkill(id=tool.name, name=tool.name, description=tool.description, tags=[]))
        return self._generate_a2a_card(agent_name=self.name, description=self.agent.instructions, skills=skills)


class OpenAIModule(Module):
    """
    OpenAIModule class provides a module for OpenAI Agents SDK based agents.
    """

    def __init__(self, agents: list[Agent], runner: OpenAIRunner = None):
        """
        Initializes an OpenAIModule instance.
        :param agents: List of agents in the module.
        :param runner: Custom runner associated with the module.
        """
        super().__init__()
        if runner is not None:
            self.runner = runner
        elif AKConfig.get().trace.enabled:
            self.runner = Trace.get().openai()
        else:
            self.runner = OpenAIRunner()
        self.load(agents)

    def _wrap(self, agent: Agent, agents: List[Agent]) -> BaseAgent:
        """
        Wraps the provided agent in an OpenAIAgent instance.
        :param agent: Agent to wrap.
        :param agents: List of agents in the module.
        :return: OpenAIAgent instance.
        """
        return OpenAIAgent(agent.name, self.runner, agent)

    def load(self, agents: list[Agent]) -> OpenAIModule:
        """
        Loads the specified agents into the module. By replacing the current agents.
        :param agents: List of agents to load.
        :return: OpenAIModule instance.
        """
        super().load(agents)
        return self

    def pre_hook(self, agent: Agent, hooks: list[PreHook]) -> "OpenAIModule":
        """
        Attaches pre-execution hooks to the agent.
        :param agent: The agent to attach hooks to.
        :param hooks: List of pre-execution hooks to attach.
        :return: OpenAIModule instance.
        """
        super().get_agent(agent.name).attach_pre_hooks(hooks)
        return self

    def post_hook(self, agent: Agent, hooks: list[PostHook]) -> "OpenAIModule":
        """
        Attaches post-execution hooks to the agent.
        :param agent: The agent to attach hooks to.
        :param hooks: List of post-execution hooks to attach.
        :return: OpenAIModule instance.
        """
        super().get_agent(agent.name).attach_post_hooks(hooks)
        return self
