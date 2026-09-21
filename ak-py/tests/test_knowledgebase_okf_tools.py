"""The OKF agent surface end to end (#553 iteration 12).

This is where the capability becomes real: a block in config.yaml plus an agent name, and the
agent has tools and instructions nobody wired. Three properties carry the weight.

Write permission is per (agent, database), so an agent that produces into one bundle and only
consumes another must be refused on exactly one of them -- and refused with a *string*, never an
exception into the framework.

Read scoping is structural rather than checked: a database an agent holds no role in is simply
not in its builder, so the existing unknown-backend message does the work. That is asserted
here so a future "improvement" that adds an explicit check has something to contradict.

And nothing is walked until it is used. get_tools() decides the tool set from configuration
alone, because doing otherwise would move a store walk per bundle into every agent's
construction.

Every bundle here is a LocalDocumentStore over tmp_path. No network, no bucket.
"""

import logging

import pytest

from agentkernel.core.config import AKConfig, _OKFConfig, _OKFDatabaseConfig
from agentkernel.core.model import SystemTool
from agentkernel.core.tool import SystemToolFactory
from agentkernel.knowledgebase.knowledgebuilder import KnowledgeBuilder
from agentkernel.knowledgebase.okf.capability import OKFCapabilityManager
from agentkernel.knowledgebase.okf.prompts import OKFPromptComposer
from agentkernel.knowledgebase.okf.tools import OKFToolFactory
from agentkernel.knowledgebase.store import LocalDocumentStore

CONCEPT = """---
type: BigQuery Table
title: Orders
description: One row per completed purchase.
tags: [sales]
verified: [{by: "human:jsmith"}]
---
# Schema
order rows
"""

BUNDLE = {
    "index.md": '---\nokf_version: "0.2"\n---\n# Root listing\n- orders\n',
    "tables/index.md": "# Curated tables\n- orders\n",
    "tables/orders.md": CONCEPT,
}

READ_TOOLS = ["get_schemas", "read_kb", "get_all_kb_descriptions", "search_kb", "fetch_kb", "browse_kb"]
WRITE_TOOLS = ["get_schemas", "read_kb", "write_kb", "get_all_kb_descriptions", "search_kb", "fetch_kb", "browse_kb"]


@pytest.fixture(autouse=True)
def reset_singletons():
    AKConfig._reset()
    OKFCapabilityManager.reset()
    yield
    AKConfig._reset()
    OKFCapabilityManager.reset()


def write_bundle(root, name="bundle", files=None) -> str:
    """Materialise a bundle on disk and return its root as a string."""
    base = root / name
    for path, text in (files if files is not None else BUNDLE).items():
        target = base / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return str(base)


def configure(monkeypatch, databases: dict) -> None:
    """Point AKConfig at an okf block carrying the given databases."""
    base = AKConfig.get()
    block = _OKFConfig(databases=databases)
    monkeypatch.setattr(AKConfig, "get", classmethod(lambda cls: base.model_copy(update={"okf": block})))


def names(tools: list) -> list:
    return [tool.name for tool in tools]


def tool_named(tools: list, name: str):
    for tool in tools:
        if tool.name == name:
            return tool.func
    raise AssertionError(f"{name} was not emitted; got {names(tools)}")


class TestToolSet:
    def test_no_block_means_no_tools(self, monkeypatch):
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")

        assert OKFToolFactory.get_tools("anyone") == []

    def test_an_agent_named_in_no_database_gets_nothing(self, monkeypatch, tmp_path):
        configure(monkeypatch, {"warehouse": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path), consumer=["reader"])})

        assert OKFToolFactory.get_tools("stranger") == []

    def test_an_unnamed_agent_gets_nothing(self, monkeypatch, tmp_path):
        configure(monkeypatch, {"warehouse": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path), consumer=["reader"])})

        assert OKFToolFactory.get_tools(None) == []

    def test_a_consumer_gets_the_six_read_tools(self, monkeypatch, tmp_path):
        configure(monkeypatch, {"warehouse": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path), consumer=["reader"])})

        assert names(OKFToolFactory.get_tools("reader")) == READ_TOOLS

    @pytest.mark.parametrize("role", ["producer", "curator"])
    def test_a_writable_role_gets_seven_tools(self, monkeypatch, tmp_path, role):
        configure(monkeypatch, {"warehouse": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path), **{role: ["agent"]})})

        assert names(OKFToolFactory.get_tools("agent")) == WRITE_TOOLS

    def test_write_kb_is_granted_by_any_writable_database(self, monkeypatch, tmp_path):
        # The tool's presence is per agent; whether a given call succeeds is per (agent, database).
        configure(
            monkeypatch,
            {
                "warehouse": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path, "warehouse"), producer=["agent"]),
                "policies": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path, "policies"), consumer=["agent"]),
            },
        )

        assert "write_kb" in names(OKFToolFactory.get_tools("agent"))

    def test_func_name_equals_system_tool_name_for_every_tool(self, monkeypatch, tmp_path):
        # The AnalyzeAttachmentsTool regression: frameworks key a tool by one and bind the other.
        configure(monkeypatch, {"warehouse": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path), producer=["agent"])})

        for tool in OKFToolFactory.get_tools("agent"):
            assert isinstance(tool, SystemTool)
            assert tool.func.__name__ == tool.name

    def test_every_tool_carries_an_agent_facing_docstring(self, monkeypatch, tmp_path):
        # The docstrings become the LLM-facing schemas when the tools are bound.
        configure(monkeypatch, {"warehouse": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path), producer=["agent"])})

        for tool in OKFToolFactory.get_tools("agent"):
            assert tool.func.__doc__ and tool.func.__doc__.strip()


class TestLaziness:
    def test_get_tools_walks_no_store(self, monkeypatch, tmp_path):
        # Otherwise every configured bundle is walked once per agent constructed.
        walks = []
        monkeypatch.setattr(LocalDocumentStore, "list", lambda self, prefix="": walks.append(prefix) or [])
        configure(monkeypatch, {"warehouse": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path), consumer=["reader"])})

        assert names(OKFToolFactory.get_tools("reader")) == READ_TOOLS
        assert walks == []

    def test_the_bundle_is_walked_on_first_use(self, monkeypatch, tmp_path):
        configure(monkeypatch, {"warehouse": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path), consumer=["reader"])})

        browse_kb = tool_named(OKFToolFactory.get_tools("reader"), "browse_kb")

        # A browse at the root returns the bundle's curated index.md verbatim, which is only
        # available once the store has actually been walked.
        assert "Root listing" in browse_kb("warehouse", "")

    def test_two_agents_over_one_database_share_a_single_manager(self, monkeypatch, tmp_path):
        configure(
            monkeypatch,
            {"warehouse": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path), consumer=["reader"], producer=["writer"])},
        )
        manager = OKFCapabilityManager.get()

        tool_named(OKFToolFactory.get_tools("reader"), "browse_kb")("warehouse", "")
        tool_named(OKFToolFactory.get_tools("writer"), "browse_kb")("warehouse", "")

        # One walk and one refresh cycle for the bundle, not one per agent.
        assert manager.builder_for("reader").backends["warehouse"] is manager.builder_for("writer").backends["warehouse"]

    def test_an_agents_tools_are_built_once_and_reused(self, monkeypatch, tmp_path):
        # KnowledgeBuilder.build() returns a fresh set of closures every call, and the tool
        # surface reaches for one by name on every invocation — so resolving per call rebuilt
        # all seven to use one.
        configure(monkeypatch, {"warehouse": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path), consumer=["reader"])})
        manager = OKFCapabilityManager.get()

        builds = []
        original = KnowledgeBuilder.build
        monkeypatch.setattr(KnowledgeBuilder, "build", lambda self, *a, **kw: builds.append(1) or original(self, *a, **kw))

        browse_kb = tool_named(OKFToolFactory.get_tools("reader"), "browse_kb")
        for _ in range(3):
            browse_kb("warehouse", "")

        assert len(builds) == 1
        assert manager.tools_for("reader") is manager.tools_for("reader")

    def test_each_agent_gets_its_own_tool_set(self, monkeypatch, tmp_path):
        # The cache is keyed per agent because the builder behind it is: two agents over
        # different databases must not be served each other's tools.
        configure(
            monkeypatch,
            {
                "warehouse": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path), consumer=["reader"]),
                "notes": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path / "other"), producer=["writer"]),
            },
        )
        manager = OKFCapabilityManager.get()

        assert manager.tools_for("reader") is not manager.tools_for("writer")
        assert "write_kb" in manager.tools_for("writer")
        assert manager.tools_for("nobody") == {}


class TestReadScoping:
    @pytest.fixture
    def two_databases(self, monkeypatch, tmp_path):
        configure(
            monkeypatch,
            {
                "warehouse": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path, "warehouse"), description="Warehouse.", consumer=["reader"]),
                "policies": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path, "policies"), description="Policies.", consumer=["other"]),
            },
        )

    def test_reaching_a_database_the_agent_holds_no_role_in_returns_the_unknown_backend_string(self, two_databases):
        read_kb = tool_named(OKFToolFactory.get_tools("reader"), "read_kb")

        # Structural, not checked: 'policies' is not in this agent's builder at all.
        assert read_kb("policies", "anything") == "Unknown backend 'policies'. Available: ['warehouse']"

    def test_get_schemas_lists_only_the_agents_own_databases(self, two_databases):
        schemas = tool_named(OKFToolFactory.get_tools("reader"), "get_schemas")()

        assert "warehouse" in schemas
        assert "policies" not in schemas

    def test_get_all_kb_descriptions_lists_only_the_agents_own_databases(self, two_databases):
        descriptions = tool_named(OKFToolFactory.get_tools("reader"), "get_all_kb_descriptions")()

        assert "warehouse" in descriptions
        assert "policies" not in descriptions


class TestWriteScoping:
    @pytest.fixture
    def mixed(self, monkeypatch, tmp_path):
        configure(
            monkeypatch,
            {
                "warehouse": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path, "warehouse"), producer=["agent"], consumer=["reader"]),
                "policies": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path, "policies"), consumer=["agent"]),
            },
        )

    def test_a_producer_writes_to_its_own_database(self, mixed):
        write_kb = tool_named(OKFToolFactory.get_tools("agent"), "write_kb")

        assert "Stored successfully" in write_kb("warehouse", text="A new fact about orders.")

    def test_the_written_concept_is_readable_back(self, mixed):
        # Write-through: the concept is reachable immediately, not after the next refresh.
        tools = OKFToolFactory.get_tools("agent")
        tool_named(tools, "write_kb")("warehouse", text="Refunds are processed weekly.")

        # read_kb ranks over the manifest and answers with concept lines, so the new concept
        # shows up as its synthesised path under generated/.
        found = tool_named(tools, "read_kb")("warehouse", "refunds")
        assert "generated/" in found

        # fetch_kb is the tool that returns a body, which is where the text itself lives.
        path = found.split("[", 1)[1].split("]", 1)[0]
        assert "Refunds are processed weekly." in tool_named(tools, "fetch_kb")("warehouse", path)

    def test_a_consumer_of_one_database_is_refused_on_that_one_only(self, mixed):
        write_kb = tool_named(OKFToolFactory.get_tools("agent"), "write_kb")

        result = write_kb("policies", text="Should not land.")

        assert result == "Agent 'agent' has read-only access to 'policies'. Knowledge bases it may write to: ['warehouse']."

    def test_the_refusal_is_a_string_not_an_exception(self, mixed):
        # The tool boundary contract: nothing raises into the framework.
        assert isinstance(tool_named(OKFToolFactory.get_tools("agent"), "write_kb")("policies", text="x"), str)

    def test_a_consumer_never_receives_write_kb_at_all(self, mixed):
        # An advertised tool it may never use is prompt surface spent on a dead end.
        assert "write_kb" not in names(OKFToolFactory.get_tools("reader"))


class TestPromptSuffix:
    def test_no_tool_carries_the_section(self, monkeypatch, tmp_path):
        # The instructions belong to the system prompt, not to a tool description: a future
        # change that smuggles them back onto a tool has this to contradict.
        configure(monkeypatch, {"warehouse": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path), consumer=["reader"])})

        assert all(tool.description == "" for tool in OKFToolFactory.get_tools("reader"))

    def test_the_section_is_contributed_to_the_system_prompt(self, monkeypatch, tmp_path):
        configure(monkeypatch, {"warehouse": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path), consumer=["reader"])})

        sections = SystemToolFactory.get_prompt_sections("reader")

        assert len(sections) == 1
        assert sections[0].startswith("[Organizational knowledge (OKF)]")
        assert sections[0] == SystemToolFactory.get_system_prompt_suffix("reader")

    def test_an_agent_holding_no_role_contributes_no_section(self, monkeypatch, tmp_path):
        configure(monkeypatch, {"warehouse": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path), consumer=["reader"])})

        assert SystemToolFactory.get_prompt_sections("stranger") == []

    def test_the_suffix_reaches_the_named_agent_only(self, monkeypatch, tmp_path):
        configure(monkeypatch, {"warehouse": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path), curator=["keeper"])})

        assert "Your role here is CURATOR" in SystemToolFactory.get_system_prompt_suffix("keeper")
        assert SystemToolFactory.get_system_prompt_suffix("stranger") == ""

    def test_system_tool_factory_emits_the_tools_for_a_named_agent(self, monkeypatch, tmp_path):
        configure(monkeypatch, {"warehouse": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path), producer=["writer"])})

        assert names(SystemToolFactory.get_all("writer")) == WRITE_TOOLS
        assert SystemToolFactory.get_all("stranger") == []

    def test_no_block_means_system_tool_factory_emits_nothing(self, monkeypatch):
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")

        assert SystemToolFactory.get_all("anyone") == []
        assert SystemToolFactory.get_prompt_sections("anyone") == []
        assert SystemToolFactory.get_system_prompt_suffix("anyone") == ""

    def test_the_okf_branch_does_not_import_the_kb_tier_when_the_block_is_absent(self, monkeypatch):
        # core/ never imports knowledgebase/ at module scope; a process with no okf block must
        # never pay for the tier. Asserted through the factory rather than by inspecting imports,
        # since the test module itself has already imported it.
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        monkeypatch.setattr(OKFToolFactory, "get_tools", staticmethod(lambda name: pytest.fail("the OKF branch ran with no block configured")))
        monkeypatch.setattr(
            OKFPromptComposer, "for_agent", classmethod(lambda cls, name: pytest.fail("the OKF prompt branch ran with no block configured"))
        )

        assert SystemToolFactory.get_all("anyone") == []
        assert SystemToolFactory.get_prompt_sections("anyone") == []


class TestValidation:
    def test_a_malformed_block_fails_at_the_first_get_tools(self, monkeypatch, tmp_path):
        # Not inside the first tool call, and not at import.
        from agentkernel.core.util.factory import AKConfigError

        configure(monkeypatch, {"warehouse": _OKFDatabaseConfig(type="s3", uri=write_bundle(tmp_path), consumer=["reader"])})

        with pytest.raises(AKConfigError, match="'warehouse'"):
            OKFToolFactory.get_tools("reader")

    def test_a_read_only_store_under_a_producer_warns_and_still_emits_tools(self, monkeypatch, tmp_path, caplog):
        root = write_bundle(tmp_path)
        monkeypatch.setattr(LocalDocumentStore, "writable", property(lambda self: False))
        configure(monkeypatch, {"warehouse": _OKFDatabaseConfig(type="local", uri=root, producer=["writer"])})

        with caplog.at_level(logging.WARNING, logger="ak.knowledgebase.okf"):
            tools = OKFToolFactory.get_tools("writer")

        assert "will be refused" in caplog.text
        assert names(tools) == WRITE_TOOLS


class TestCallingAgentResolution:
    def test_the_closure_name_is_used_when_no_context_is_set(self, monkeypatch, tmp_path):
        # ToolContext.get() raises outside a run and Agent.current() is None, so the closure's
        # own name must carry the refusal -- it is correct, because the tool was attached to it.
        configure(
            monkeypatch,
            {
                "warehouse": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path, "warehouse"), producer=["agent"]),
                "policies": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path, "policies"), consumer=["agent"]),
            },
        )

        assert OKFToolFactory._calling_agent() is None
        assert "Agent 'agent'" in tool_named(OKFToolFactory.get_tools("agent"), "write_kb")("policies", text="x")

    def test_a_running_agent_wins_over_the_closure_name(self, monkeypatch, tmp_path):
        # The case the re-resolution exists for: if a framework ever shares a tool object between
        # agents, the refusal must name whoever is actually calling.
        from agentkernel.core.base import Agent

        configure(
            monkeypatch,
            {
                "warehouse": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path, "warehouse"), producer=["writer"]),
                "policies": _OKFDatabaseConfig(type="local", uri=write_bundle(tmp_path, "policies"), consumer=["reader"]),
            },
        )
        write_kb = tool_named(OKFToolFactory.get_tools("writer"), "write_kb")

        class FakeAgent:
            name = "reader"

        token = Agent.current_agent.set(FakeAgent())
        try:
            result = write_kb("policies", text="x")
        finally:
            Agent.current_agent.reset(token)

        assert "Agent 'reader'" in result
