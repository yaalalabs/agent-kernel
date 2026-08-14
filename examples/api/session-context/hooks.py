"""
Post-execution hook demonstrating Session.get_framework_session().

- HistoryTrimHook: Trims the framework-native session history via Session.get_framework_session()
"""

from agentkernel import Agent, PostHook, Session
from agentkernel.core.model import AgentReply, AgentRequest


class HistoryTrimHook(PostHook):
    """
    Once the underlying OpenAI Agents SDK conversation history grows past THRESHOLD raw
    items, trims it back down to the most recent THRESHOLD items after every turn, to bound
    token usage as a session grows.

    Demonstrates Session.get_framework_session(): it returns the SAME live object each
    framework adapter stores its native session state under (keyed by the current agent's
    runner name, e.g. "openai"). Mutating it in place via its own methods is visible
    immediately - no session.set(...) call needed, since Session.get()/set() just read/write
    a live reference in a plain dict.
    """

    THRESHOLD = 3

    async def on_run(
        self, session: Session, requests: list[AgentRequest], agent: Agent, agent_reply: AgentReply
    ) -> AgentReply:
        """
        Trims the OpenAI-native item history in place after the agent has responded.
        :param session: The session instance.
        :param requests: The original requests provided to the agent after any pre-execution hooks.
        :param agent: The agent that executed the prompt.
        :param agent_reply: The reply to process.
        :return: The unmodified reply - this hook only trims session state, not the response.
        """
        openai_session = session.get_framework_session()
        if openai_session is None:
            return agent_reply  # Nothing stored yet - e.g. the agent isn't OpenAI-based.

        items = await openai_session.get_items()
        if len(items) > self.THRESHOLD:
            capped = items[-self.THRESHOLD :]  # keep only the most recent THRESHOLD items
            await openai_session.clear_session()
            await openai_session.add_items(capped)

        return agent_reply

    def name(self) -> str:
        return "HistoryTrimHook"
