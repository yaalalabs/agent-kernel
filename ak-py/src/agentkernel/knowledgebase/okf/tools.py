"""The agent-facing surface of the OKF capability.

Registered on the agents the ``okf`` block names (via ``SystemToolFactory``), so an application
that configures a bundle and names its agents gets the tools and the instructions without
wiring a store, a backend or a ``KnowledgeBuilder`` itself.

Two scoping rules, enforced in two different ways:

* **Reads are scoped structurally.** An agent's ``KnowledgeBuilder`` registers only the
  databases it holds a role in, so reaching for another one already returns the builder's own
  ``"Unknown backend ..."`` string. Nothing here checks it.
* **Writes need one check**, because an agent may hold write on one of its *own* databases and
  only read on another. That check is per ``(agent, database)`` pair and runs at call time.

Every tool body is a closure over the agent name alone and resolves its builder when called, so
agent construction neither opens a store nor walks a bundle.

The capability's instructions are not here: they are a system prompt section, composed by
``OKFPromptComposer.for_agent`` and appended to the agent's own prompt.
"""

from typing import Any, List, Optional

from ...core.model import SystemTool
from ..knowledgebuilder import KnowledgeBuilder
from .capability import OKFCapabilityManager

_NO_KB = "No OKF knowledge base is configured for this agent."


class OKFToolFactory:
    """Builds one agent's OKF system tools from the configured roles."""

    @staticmethod
    def get_tools(agent_name: Optional[str]) -> List[SystemTool]:
        """
        Build the OKF system tools for one agent.

        :param agent_name: Agent the tools are being attached to.
        :return: The tools, or an empty list when the capability is off or the agent holds no role.
        """
        manager = OKFCapabilityManager.get()
        if manager is None or not agent_name or not manager.roles.has_any_role(agent_name):
            return []

        # Forces the store-resolution checks once per process, so a malformed block fails at the
        # first agent construction naming the offending database, rather than inside a tool call.
        manager.validate_configuration()

        writable = bool(manager.roles.writable_databases_for(agent_name))

        # Every description is "": the capability's instructions are a system prompt section
        # (``OKFPromptComposer.for_agent``, collected by ``SystemToolFactory.get_prompt_sections``)
        # written into the agent's prompt, not a payload smuggled through a tool description --
        # which no framework reads anyway, since the tool builders bind ``func.__doc__``.
        return [SystemTool(name=func.__name__, description="", func=func) for func in OKFToolFactory._build(agent_name, writable)]

    @staticmethod
    def _build(agent_name: str, writable: bool) -> List[Any]:
        """
        Build the plain callables, each closing over the agent name only.

        The names are the function names, because ``SystemTool.name`` must equal
        ``func.__name__`` for the frameworks that key a tool by one and bind the other.

        :param agent_name: Agent the closures resolve their builder for.
        :param writable: Whether to include ``write_kb``.
        :return: The callables, in the order they are advertised.
        """

        def get_schemas() -> str:
            """
            Retrieve the schema and metadata for every knowledge base available to you.

            :return: JSON string containing each backend's schema definition.
            """
            return OKFToolFactory._call(agent_name, "get_schemas")

        def read_kb(backend: str, query: str, limit: int = 3) -> str:
            """
            Read from a knowledge base, letting it decide how to interpret your text.

            :param backend: Backend name, as returned by get_schemas().
            :param query: What you are looking for.
            :param limit: Maximum number of results to return.
            :return: Formatted result string or error message.
            """
            return OKFToolFactory._call(agent_name, "read_kb", backend, query, limit)

        def get_all_kb_descriptions() -> str:
            """
            Retrieve a short description of every knowledge base available to you.

            :return: Newline-delimited descriptions.
            """
            return OKFToolFactory._call(agent_name, "get_all_kb_descriptions")

        def search_kb(backend: str, query: str, limit: int = 3) -> str:
            """
            Find the knowledge most relevant to a natural-language question.

            :param backend: Backend name, as returned by get_schemas().
            :param query: Natural-language description of what you are looking for.
            :param limit: Maximum number of results to return.
            :return: Formatted search result string or error message.
            """
            return OKFToolFactory._call(agent_name, "search_kb", backend, query, limit)

        def fetch_kb(backend: str, ids: str) -> str:
            """
            Retrieve specific concepts by the paths a previous result showed.

            Paths appear in square brackets at the start of each result line. This is the only
            tool that returns a concept's full body and its links to other concepts.

            :param backend: Backend name, as returned by get_schemas().
            :param ids: One concept path, or several separated by commas.
            :return: Formatted records string or error message.
            """
            return OKFToolFactory._call(agent_name, "fetch_kb", backend, ids)

        def browse_kb(backend: str, path: str = "", limit: int = 50) -> str:
            """
            List what a knowledge base holds under a namespace, without searching it.

            :param backend: Backend name, as returned by get_schemas().
            :param path: Namespace to list; empty lists the top level.
            :param limit: Maximum number of entries to return.
            :return: Formatted listing string or error message.
            """
            return OKFToolFactory._call(agent_name, "browse_kb", backend, path, limit)

        def write_kb(backend: str, text: str = "", source: str = "agent", query: str = "", params_json: str = "{}") -> str:
            """
            Persist knowledge into a knowledge base you may write to.

            :param backend: Backend name, as returned by get_schemas().
            :param text: The knowledge to record.
            :param source: Origin label for the written record.
            :param query: Optional backend-specific write query; unused by OKF bundles.
            :param params_json: JSON object string of query parameters.
            :return: Success message, or a message explaining why the write was refused.
            """
            manager = OKFCapabilityManager.get()
            if manager is None:
                return _NO_KB

            # Re-resolved rather than taken from the closure: the closure's name decides which
            # tools were attached, while this decides who is actually calling, which is what
            # keeps the refusal honest if a framework ever shares a tool object between agents.
            caller = OKFToolFactory._calling_agent() or agent_name
            if not manager.roles.may_write(caller, backend):
                writable_databases = sorted(manager.roles.writable_databases_for(caller))
                return f"Agent '{caller}' has read-only access to '{backend}'. " f"Knowledge bases it may write to: {writable_databases}."
            return OKFToolFactory._call(caller, "write_kb", backend, text, source, query, params_json)

        ordered = [get_schemas, read_kb, get_all_kb_descriptions, search_kb, fetch_kb, browse_kb]
        if writable:
            # Index 2, the position write_kb holds in KnowledgeBuilder's own ordering.
            ordered.insert(2, write_kb)
        return ordered

    @staticmethod
    def _call(agent_name: str, tool_name: str, *args) -> str:
        """
        Resolve the agent's builder and invoke one of its tools.

        Resolution happens per call rather than per construction, so a bundle is opened the
        first time an agent actually reaches for it and a configuration edited in between is
        still honoured.

        :param agent_name: Agent whose builder to use.
        :param tool_name: Name of the KnowledgeBuilder tool to invoke.
        :param args: Positional arguments forwarded to it.
        :return: Whatever the tool returned, or an explanation when there is no builder.
        """
        builder = OKFToolFactory._builder(agent_name)
        if builder is None:
            return _NO_KB

        for tool in builder.build(writable=True):
            if tool.__name__ == tool_name:
                return tool(*args)
        # Reachable only if a backend stopped declaring a capability between construction and
        # this call; reported rather than raised, like every other tool-boundary failure.
        return f"'{tool_name}' is not available for this agent's knowledge bases."

    @staticmethod
    def _builder(agent_name: str) -> Optional[KnowledgeBuilder]:
        """
        Return the agent's builder, or None when the capability is off or it holds no role.

        :param agent_name: Agent to resolve for.
        :return: The builder, or None.
        """
        manager = OKFCapabilityManager.get()
        return manager.builder_for(agent_name) if manager else None

    @staticmethod
    def _calling_agent() -> Optional[str]:
        """
        Resolve the name of the agent currently executing, if it can be determined.

        ``ToolContext.get()`` raises when no context is set, and ``Agent.current()`` is None
        outside a run, so both are guarded. The caller falls back to the name the closure was
        built with, which is correct whenever the context is missing -- the tool was attached
        to that agent.

        :return: The calling agent's name, or None when neither source is populated.
        """
        from ...core.base import Agent
        from ...core.tool import ToolContext

        try:
            return ToolContext.get().agent.name
        except (RuntimeError, AttributeError):
            pass

        current = Agent.current()
        return current.name if current else None
