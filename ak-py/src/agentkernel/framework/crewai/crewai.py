import logging
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any, Callable, List

from crewai import Agent, Crew, Memory, Task
from crewai.memory import MemoryRecord, ScopeInfo
from crewai.memory.storage.backend import StorageBackend as Storage
from crewai.tools import tool as crewai_tool
from pydantic import BaseModel

from ...core import Agent as BaseAgent
from ...core import Module, PostHook, PreHook, Runner, Runtime, Session, ToolBuilder, ToolContext
from ...core.builder import A2ACardBuilder
from ...core.config import AKConfig
from ...core.event import StreamEvent
from ...core.model import AgentReply, AgentReplyAny, AgentReplyText, AgentRequest, AgentRequestAny, AgentRequestText
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

    TRANSCRIPT_KEY = f"{FRAMEWORK}_transcript"
    """
    Session data key holding the conversation transcript.
    """
    TRANSCRIPT_MAX_LINES = 20
    """
    Maximum number of transcript lines (user and assistant entries) kept in the session.
    """

    def __init__(self):
        """
        Initializes a CrewAIRunner instance.
        """
        super().__init__(FRAMEWORK)
        self._log = logging.getLogger("ak.crewai.runner")
        self._context_warned = False
        """Whether the unsupported-framework_context warning was already logged."""

    def _transcript(self, session: Session) -> list[str] | None:
        """
        Returns the conversation transcript associated with the session.
        The transcript keeps the recent user prompts and agent replies as plain text so
        follow-up prompts can be answered with deterministic conversational context,
        independent of memory embedding or recall behaviour.
        :param session: The session to retrieve the transcript for.
        :return: The transcript for the session, or None if no session is provided.
        """
        if session is None:
            return None
        transcript = session.get(self.TRANSCRIPT_KEY)
        if transcript is None:
            transcript = session.set(self.TRANSCRIPT_KEY, [])
        return transcript

    @staticmethod
    def _describe(prompt: str, transcript: list[str] | None) -> str:
        """
        Builds the task description for the prompt, prepending the recent conversation
        so the agent can resolve references to earlier turns.
        :param prompt: The current user prompt.
        :param transcript: The conversation transcript, if any.
        :return: The task description.
        """
        if not transcript:
            return prompt
        history = "\n".join(transcript)
        return f"Previous conversation:\n{history}\n\nCurrent request:\n{prompt}"

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
                    prompt = prompt + "\n" + req.prompt if prompt else req.prompt
                else:
                    return AgentReplyText(
                        response="Sorry. Agent kernel CrewAI runner is unable to handle content other than text at the moment",
                        prompt=prompt,
                    )

            if prompt.strip() == "":
                return AgentReplyText(response="Sorry. No valid text prompt found in the requests")

            memory = self._memory(session)
            if memory:
                try:
                    memory.remember(content=prompt)
                except Exception as e:
                    # Memory is an enrichment on top of the transcript; a failure (e.g. no
                    # embedder configured) must not fail the run.
                    self._log.warning(f"Unable to persist prompt to CrewAI memory, continuing without memory: {e}")
                    memory = None

            transcript = self._transcript(session)
            output_pydantic = getattr(agent, "output_pydantic", None)
            output_json = getattr(agent, "output_json", None)
            schema = output_pydantic or output_json
            expected_output = f"A structured response conforming to the {schema.__name__} schema" if schema is not None else "An answer is plain text"
            task = Task(
                description=self._describe(prompt, transcript),
                expected_output=expected_output,
                agent=agent.agent,
                output_pydantic=output_pydantic,
                output_json=output_json,
            )
            crew = Crew(
                agents=agent.crew,
                tasks=[task],
                verbose=False,
                memory=memory,
            )
            # CrewAI's kickoff(inputs=...) are template-interpolation variables, not a context/state object, so
            # there is no per-run caller-state slot. Warn once, and leave the stored context untouched.
            if not self._context_warned and session is not None and session.get_framework_context():
                self._log.warning("framework_context is set but CrewAI does not support per-run caller context/state; ignoring it.")
                self._context_warned = True
            reply = await crew.kickoff_async(inputs={})
            if isinstance(getattr(reply, "pydantic", None), BaseModel):
                agent_reply: AgentReply = AgentReplyAny(content=reply.pydantic.model_dump(mode="json"), prompt=prompt)
            elif isinstance(getattr(reply, "json_dict", None), dict):
                agent_reply = AgentReplyAny(content=reply.json_dict, prompt=prompt)
            else:
                if hasattr(reply, "raw"):
                    raw_reply = reply.raw
                    reply_text = "" if raw_reply is None else str(raw_reply)
                else:
                    reply_text = "" if reply is None else str(reply)
                agent_reply = AgentReplyText(response=reply_text, prompt=prompt)

            if transcript is not None:
                transcript.append(f"User: {prompt}")
                transcript.append(f"Assistant: {str(agent_reply)}")
                del transcript[: -self.TRANSCRIPT_MAX_LINES]

            return agent_reply
        except Exception as e:
            return AgentReplyText(response=user_facing_error_message(e), prompt=prompt)
        finally:
            if context is not None:
                context.reset()

    @property
    def supports_streaming(self) -> bool:
        """
        :return: False — this adapter does not implement streaming, so stream() always raises.
        """
        return False

    async def stream(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AsyncGenerator[StreamEvent, None]:
        """
        CrewAI does not support SSE streaming.
        :raises NotImplementedError: Always raised — use rest_sync mode instead.
        """
        raise NotImplementedError("CrewAI does not support SSE streaming. Use rest_sync mode.")
        yield  # make this an async generator to satisfy the type contract


class CrewAIAgent(BaseAgent):
    """
    CrewAIAgent class provides an agent wrapping for CrewAI based agents.
    """

    def __init__(
        self,
        name: str,
        runner: CrewAIRunner,
        agent: Agent,
        crew: list[Agent],
        output_pydantic: type[BaseModel] | None = None,
        output_json: type[BaseModel] | None = None,
    ):
        """
        Initializes a CrewAIAgent instance.
        :param name: Name of the agent.
        :param runner: Runner associated with the agent.
        :param agent: The CrewAI agent instance.
        :param crew: List of CrewAI agents in the crew.
        :param output_pydantic: Optional Pydantic model class forwarded to the Task built per run,
        making the agent produce structured output (returned as an AgentReplyAny).
        :param output_json: Optional Pydantic model class forwarded to the Task built per run as its
        JSON output schema (returned as an AgentReplyAny).
        """
        super().__init__(name, runner)
        self._agent = agent
        self._crew = crew
        self._output_pydantic = output_pydantic
        self._output_json = output_json
        self._attach_system_tools()
        self._setup_system_prompt()

    @property
    def agent(self) -> Agent:
        """
        Returns the CrewAI agent instance.
        """
        return self._agent

    @property
    def output_pydantic(self) -> type[BaseModel] | None:
        """
        Returns the Pydantic model class used for structured task output, if configured.
        """
        return self._output_pydantic

    @output_pydantic.setter
    def output_pydantic(self, model: type[BaseModel] | None) -> None:
        """
        Sets the Pydantic model class forwarded to the Task built per run.
        :param model: The Pydantic model class, or None to disable structured output.
        """
        self._output_pydantic = model

    @property
    def output_json(self) -> type[BaseModel] | None:
        """
        Returns the Pydantic model class used as the JSON output schema, if configured.
        """
        return self._output_json

    @output_json.setter
    def output_json(self, model: type[BaseModel] | None) -> None:
        """
        Sets the Pydantic model class forwarded to the Task built per run as its JSON output schema.
        :param model: The Pydantic model class, or None to disable structured output.
        """
        self._output_json = model

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
        self._append_tools(self.agent, CrewAIToolBuilder.bind([tool]))

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

    def __init__(
        self,
        agents: list[Agent],
        runner: CrewAIRunner = None,
        output_pydantic: dict[str, type[BaseModel]] | None = None,
        output_json: dict[str, type[BaseModel]] | None = None,
    ):
        """
        Initializes a CrewAIModule instance.
        :param agents: List of agents in the module.
        :param runner: Custom runner associated with the module.
        :param output_pydantic: Optional mapping of agent role to the Pydantic model class forwarded
        to the Task built per run, making the agent produce structured output (returned as an
        AgentReplyAny).
        :param output_json: Optional mapping of agent role to the Pydantic model class forwarded to
        the Task built per run as its JSON output schema (returned as an AgentReplyAny).
        """
        super().__init__()
        if runner is not None:
            self.runner = runner
        elif AKConfig.get().trace.enabled:
            self.runner = Trace.get().crewai()
        else:
            self.runner = CrewAIRunner()
        self._output_pydantic = output_pydantic or {}
        self._output_json = output_json or {}
        self.load(agents)

    def _wrap(self, agent: Agent, agents: List[Agent]) -> BaseAgent:
        """
        Wraps the provided agent in a CrewAIAgent instance.
        :param agent: Agent to wrap.
        :param agents: List of agents in the module.
        :return: CrewAIAgent instance.
        """
        return CrewAIAgent(
            agent.role,
            self.runner,
            agent,
            agents,
            output_pydantic=self._output_pydantic.get(agent.role),
            output_json=self._output_json.get(agent.role),
        )

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
