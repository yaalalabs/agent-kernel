import logging
from datetime import datetime
from typing import Any, Callable, List

from crewai import Agent, Crew, Memory, Task
from crewai.memory import MemoryRecord, ScopeInfo

try:
    from crewai.events.listeners.tracing.utils import set_suppress_tracing_messages

    set_suppress_tracing_messages(True)
except ImportError:
    pass

from crewai.memory.storage.backend import StorageBackend as Storage
from crewai.tools import tool as crewai_tool

from ...core import Agent as BaseAgent
from ...core import Module, PostHook, PreHook, Runner, Runtime, Session, ToolBuilder, ToolContext
from ...core.builder import A2ACardBuilder
from ...core.config import AKConfig
from ...core.model import AgentReply, AgentReplyText, AgentRequest, AgentRequestAny, AgentRequestText
from ...core.util.error_util import user_facing_error_message
from ...trace import Trace

FRAMEWORK = "crewai"


class CrewAISession(Storage):
    """
    CrewAISession class provides a session for CrewAI based agents.
    """

    def __init__(self):
        """
        Initializes a CrewAISession instance.
        """
        self._items: list[MemoryRecord] = []
        self._log = logging.getLogger("ak.crewai.session")

    @staticmethod
    def _normalize_scope(scope: str | None) -> str:
        if not scope:
            return "/"
        normalized = scope if scope.startswith("/") else f"/{scope}"
        return normalized.rstrip("/") or "/"

    @classmethod
    def _is_in_scope(cls, record_scope: str, scope_prefix: str | None) -> bool:
        if scope_prefix is None:
            return True
        normalized_scope = cls._normalize_scope(record_scope)
        normalized_prefix = cls._normalize_scope(scope_prefix)
        return normalized_prefix == "/" or normalized_scope == normalized_prefix or normalized_scope.startswith(f"{normalized_prefix}/")

    @staticmethod
    def _metadata_matches(record: MemoryRecord, metadata_filter: dict[str, Any] | None) -> bool:
        if metadata_filter is None:
            return True
        return all(record.metadata.get(key) == value for key, value in metadata_filter.items())

    def save(self, records: list[MemoryRecord]) -> None:
        """
        Saves memory records to the session.
        :param records: The memory records to save.
        """
        self._log.debug(f"save: {records}")
        for record in records:
            stored = record.model_copy(deep=True)
            for index, existing in enumerate(self._items):
                if existing.id == stored.id:
                    self._items[index] = stored
                    break
            else:
                self._items.append(stored)

    def search(
        self,
        query_embedding: list[float],
        scope_prefix: str | None = None,
        categories: list[str] | None = None,
        metadata_filter: dict[str, Any] | None = None,
        limit: int = 10,
        min_score: float = 0.0,
    ) -> list[tuple[MemoryRecord, float]]:
        """
        Searches for memory records in the session.
        :param query_embedding: Embedding vector for the query.
        :param scope_prefix: Optional scope prefix to filter by.
        :param categories: Optional categories to filter by.
        :param metadata_filter: Optional metadata filter.
        :param limit: Maximum number of results to return.
        :param min_score: Minimum similarity score threshold.
        :return: Matching memory records with similarity scores.
        """
        self._log.debug(f"search: {scope_prefix}, {categories}, {metadata_filter}, {limit}, {min_score}")
        if limit <= 0:
            return []

        results: list[tuple[MemoryRecord, float]] = []
        for record in self._items:
            if not self._is_in_scope(record.scope, scope_prefix):
                continue
            if categories and not all(category in set(record.categories) for category in categories):
                continue
            if not self._metadata_matches(record, metadata_filter):
                continue

            if not query_embedding or not record.embedding:
                score = 1.0
            else:
                length = min(len(query_embedding), len(record.embedding))
                query = query_embedding[:length]
                embedding = record.embedding[:length]
                dot = sum(left * right for left, right in zip(query, embedding))
                query_norm = sum(value * value for value in query) ** 0.5
                embedding_norm = sum(value * value for value in embedding) ** 0.5
                score = 0.0 if query_norm == 0 or embedding_norm == 0 else dot / (query_norm * embedding_norm)

            if score >= min_score:
                results.append((record.model_copy(deep=True), score))

        results.sort(key=lambda item: (item[1], item[0].created_at), reverse=True)
        return results[:limit]

    def reset(self, scope_prefix: str | None = None) -> None:
        """
        Resets the session by clearing all items.
        :param scope_prefix: Optional scope prefix to reset.
        """
        self._log.debug(f"reset: {scope_prefix}")
        if scope_prefix is None:
            self._items = []
            return
        self._items = [record for record in self._items if not self._is_in_scope(record.scope, scope_prefix)]

    def list_scopes(self, parent: str = "/") -> list[str]:
        """
        Lists immediate child scopes under the parent scope.
        :param parent: Parent scope path.
        :return: Immediate child scope paths.
        """
        normalized_parent = self._normalize_scope(parent)
        children: set[str] = set()
        for record in self._items:
            scope = self._normalize_scope(record.scope)
            if normalized_parent == "/":
                remainder = scope.strip("/")
            elif scope.startswith(f"{normalized_parent}/"):
                remainder = scope[len(normalized_parent) + 1 :]
            else:
                continue
            if remainder:
                children.add(f"{normalized_parent.rstrip('/')}/{remainder.split('/')[0]}")
        return sorted(children)

    def list_categories(self, scope_prefix: str | None = None) -> dict[str, int]:
        """
        Lists categories and their counts within a scope.
        :param scope_prefix: Optional scope prefix to filter by.
        :return: Mapping of category name to record count.
        """
        categories: dict[str, int] = {}
        for record in self._items:
            if not self._is_in_scope(record.scope, scope_prefix):
                continue
            for category in record.categories:
                categories[category] = categories.get(category, 0) + 1
        return categories

    def get_scope_info(self, scope: str) -> ScopeInfo:
        """
        Returns summary information for a scope.
        :param scope: Scope path.
        :return: Scope information.
        """
        normalized_scope = self._normalize_scope(scope)
        records = [record for record in self._items if self._is_in_scope(record.scope, normalized_scope)]
        categories = sorted({category for record in records for category in record.categories})
        created_at = [record.created_at for record in records]
        return ScopeInfo(
            path=normalized_scope,
            record_count=len(records),
            categories=categories,
            oldest_record=min(created_at) if created_at else None,
            newest_record=max(created_at) if created_at else None,
            child_scopes=self.list_scopes(normalized_scope),
        )

    def list_records(self, scope_prefix: str | None = None, limit: int = 200, offset: int = 0) -> list[MemoryRecord]:
        """
        Lists stored memory records.
        :param scope_prefix: Optional scope prefix to filter by.
        :param limit: Maximum number of records to return.
        :param offset: Number of records to skip.
        :return: Matching memory records.
        """
        if limit <= 0:
            return []
        records = [record for record in self._items if self._is_in_scope(record.scope, scope_prefix)]
        return [record.model_copy(deep=True) for record in records[offset : offset + limit]]

    def count(self, scope_prefix: str | None = None) -> int:
        """
        Counts stored memory records.
        :param scope_prefix: Optional scope prefix to filter by.
        :return: Number of matching records.
        """
        return len([record for record in self._items if self._is_in_scope(record.scope, scope_prefix)])

    def delete(
        self,
        scope_prefix: str | None = None,
        categories: list[str] | None = None,
        record_ids: list[str] | None = None,
        older_than: datetime | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> int:
        """
        Deletes matching memory records.
        :return: Number of records deleted.
        """
        remaining: list[MemoryRecord] = []
        deleted = 0
        record_id_set = set(record_ids) if record_ids else None
        for record in self._items:
            matches = self._is_in_scope(record.scope, scope_prefix)
            matches = matches and (record_id_set is None or record.id in record_id_set)
            matches = matches and (not categories or all(category in set(record.categories) for category in categories))
            matches = matches and (older_than is None or record.created_at < older_than)
            matches = matches and self._metadata_matches(record, metadata_filter)
            if matches:
                deleted += 1
            else:
                remaining.append(record)
        self._items = remaining
        return deleted

    def update(self, record: MemoryRecord) -> None:
        """
        Updates an existing memory record.
        :param record: Memory record to update.
        """
        for index, existing in enumerate(self._items):
            if existing.id == record.id:
                self._items[index] = record.model_copy(deep=True)
                return
        self._items.append(record.model_copy(deep=True))

    def get_record(self, record_id: str) -> MemoryRecord | None:
        """
        Returns a memory record by id.
        :param record_id: Memory record id.
        :return: Matching memory record, if any.
        """
        for record in self._items:
            if record.id == record_id:
                return record.model_copy(deep=True)
        return None


class CrewAIRunner(Runner):
    """
    CrewAIRunner class provides a runner for CrewAI based agents.
    """

    def __init__(self):
        """
        Initializes a CrewAIRunner instance.
        """
        super().__init__(FRAMEWORK)
        self._log = logging.getLogger("ak.crewai.runner")

    def _memory(self, session: Session) -> Memory | None:
        """
        Returns the unified memory associated with the session.
        :param session: The session to retrieve the memory for.
        :return: The unified memory for the session, or None if the session is not provided.
        """
        if session is None:
            self._log.debug("Running without session")
            return None
        if session.get(FRAMEWORK) is None:
            self._log.debug("Creating new CrewAISession")
            previous = session.set(FRAMEWORK, CrewAISession())
        else:
            self._log.debug("Reusing existing CrewAISession")
            previous = session.get(FRAMEWORK)
        return Memory(storage=previous)

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the CrewAI agent with provided multi modal inputs.
        :param agent: The CrewAI agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        prompt = ""
        context: ToolContext | None = None
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            for req in requests:
                if isinstance(req, AgentRequestAny):  # AgentRequestAny is handled only by pre-hooks, not by the agent itself
                    continue
                if isinstance(req, AgentRequestText):
                    prompt = prompt + "\n" + req.text if prompt else req.text
                else:
                    return AgentReplyText(
                        text="Sorry. Agent kernel CrewAI runner is unable to handle content other than text at the moment",
                        prompt=prompt,
                    )

            if prompt.strip() == "":
                return AgentReplyText(text="Sorry. No valid text prompt found in the requests")

            memory = self._memory(session)

            task = Task(
                description=prompt,
                expected_output="An answer is plain text",
                agent=agent.agent,
            )
            crew = Crew(
                agents=agent.crew,
                tasks=[task],
                verbose=False,
                memory=memory,
            )
            reply = await crew.kickoff_async(inputs={})
            if hasattr(reply, "raw"):
                raw_reply = reply.raw
                reply_text = "" if raw_reply is None else str(raw_reply)
            else:
                reply_text = "" if reply is None else str(reply)

            return AgentReplyText(text=reply_text, prompt=prompt)
        except Exception as e:
            return AgentReplyText(text=user_facing_error_message(e), prompt=prompt)
        finally:
            if context is not None:
                context.reset()


class CrewAIAgent(BaseAgent):
    """
    CrewAIAgent class provides an agent wrapping for CrewAI based agents.
    """

    def __init__(self, name: str, runner: CrewAIRunner, agent: Agent, crew: list[Agent]):
        """
        Initializes a CrewAIAgent instance.
        :param name: Name of the agent.
        :param runner: Runner associated with the agent.
        :param agent: The CrewAI agent instance.
        :param crew: List of CrewAI agents in the crew.
        """
        super().__init__(name, runner)
        self._agent = agent
        self._crew = crew
        self._attach_system_tools()
        self._setup_system_prompt()

    @property
    def agent(self) -> Agent:
        """
        Returns the CrewAI agent instance.
        """
        return self._agent

    @property
    def crew(self) -> list[Agent]:
        """
        Returns the list of CrewAI agents in the crew.
        """
        return self._crew

    def get_description(self):
        """
        Returns the description of the agent.
        """
        return self.agent.goal or self.agent.backstory

    def get_a2a_card(self):
        """
        Returns the A2A AgentCard associated with the agent.
        """
        from a2a.types import AgentSkill

        skills = []
        for tool in self.agent.tools:
            skills.append(AgentSkill(id=tool.name, name=tool.name, description=tool.description, tags=[]))
        return A2ACardBuilder.build(name=self.name, description=self.agent.backstory, skills=skills)

    def attach_tool(self, tool: Any) -> None:
        """
        Accepts a raw Callable and wraps it with CrewAIToolBuilder before attaching,
        so the base Agent._attach_system_tools() can pass raw functions generically.
        :param tool: Raw Python callable or already-wrapped CrewAI tool.
        """
        # Delegate to the tool builder to handle binding
        wrapped = CrewAIToolBuilder.bind([tool])
        for w in wrapped:
            if not hasattr(self.agent, "tools") or self.agent.tools is None:
                self.agent.tools = []
            if w not in self.agent.tools:
                self.agent.tools.append(w)

    def override_system_prompt(self, prompt: str) -> None:
        """
        Appends the given prompt text to the CrewAI agent's backstory.
        Called by the base Agent._setup_system_prompt() at init when multimodal is enabled.
        """
        if prompt not in self._agent.backstory:
            self._agent.backstory += "\n" + prompt


class CrewAIModule(Module):
    """
    CrewAIModule class provides a module for CrewAI based agents.
    """

    def __init__(self, agents: list[Agent], runner: CrewAIRunner = None):
        """
        Initializes a CrewAIModule instance.
        :param agents: List of agents in the module.
        :param runner: Custom runner associated with the module.
        """
        super().__init__()
        if runner is not None:
            self.runner = runner
        elif AKConfig.get().trace.enabled:
            self.runner = Trace.get().crewai()
        else:
            self.runner = CrewAIRunner()
        self.load(agents)

    def _wrap(self, agent: Agent, agents: List[Agent]) -> BaseAgent:
        """
        Wraps the provided agent in a CrewAIAgent instance.
        :param agent: Agent to wrap.
        :param agents: List of agents in the module.
        :return: CrewAIAgent instance.
        """
        return CrewAIAgent(agent.role, self.runner, agent, agents)

    def load(self, agents: list[Agent]) -> "CrewAIModule":
        """
        Loads the specified agents into the module. By replacing the current agents.
        :param agents: List of agents to load.
        :return: CrewAIModule instance.
        """
        super().load(agents)
        return self

    def pre_hook(self, agent: Agent, hooks: list[PreHook]) -> "CrewAIModule":
        """
        Attaches pre-execution hooks to the agent.
        :param agent: The agent to attach hooks to.
        :param hooks: List of pre-execution hooks to attach.
        :return: CrewAIModule instance.
        """
        super().get_agent(agent.role).pre_hooks.extend(hooks)
        return self

    def post_hook(self, agent: Agent, hooks: list[PostHook]) -> "CrewAIModule":
        """
        Attaches post-execution hooks to the agent.
        :param agent: The agent to attach hooks to.
        :param hooks: List of post-execution hooks to attach.
        :return: CrewAIModule instance.
        """
        super().get_agent(agent.role).post_hooks.extend(hooks)
        return self


class CrewAIToolBuilder(ToolBuilder):
    """
    Tool builder for CrewAI.

    Wraps generic tool functions into CrewAI-compatible tool definitions
    using the ``@tool`` decorator from the CrewAI SDK.
    """

    @classmethod
    def bind(cls, funcs: list[Callable]) -> list[Any]:
        """
        Bind generic tool functions to CrewAI tool definitions.

        :param funcs: List of generic tool functions to bind.
        :return: List of CrewAI-compatible tool definitions.
        :raises TypeError: If any item in funcs is not callable.
        """
        tools = []
        for func in funcs:
            if not callable(func):
                raise TypeError(f"Expected a callable, got {type(func).__name__}")
            tools.append(crewai_tool(func))
        return tools
