"""Schedule system tools (#629 Phase 4).

Two surfaces are pinned here, in the shape of the sandbox suite (tests/test_sandbox.py): the
registration surface (which agents get the tools and the prompt guidance) and each tool's JSON
contract, including the two short-circuits every tool starts with — a disabled capability and a
run with no user identity.
"""

import json

import pytest

from agentkernel.core.base import Agent, Runner, Session
from agentkernel.core.config import _ScheduleConfig
from agentkernel.core.model import AgentReplyText, ScheduleSpec
from agentkernel.core.runtime import ACTING_USER_CACHE_KEY, Runtime
from agentkernel.core.tool import SystemToolFactory
from agentkernel.schedule.manager import ScheduleManager
from agentkernel.schedule.model import ScheduleStatus
from agentkernel.schedule.provider.base import ScheduleProvider
from agentkernel.schedule.store.in_memory import InMemoryScheduleStore
from agentkernel.schedule.tools import (
    create_schedule,
    delete_schedule,
    get_schedule,
    get_schedule_tools,
    list_schedules,
    update_schedule,
)

SCHEDULE_TOOL_NAMES = ["create_schedule", "list_schedules", "get_schedule", "update_schedule", "delete_schedule"]

FUTURE_AT = "2030-06-01T09:00:00"


class RecordingScheduleProvider(ScheduleProvider):
    """Stands in for a real trigger backend: registers nothing, remembers deletions."""

    def __init__(self):
        self.deleted: list[str] = []

    def create(self, task, body_template):
        return f"ref-{task.task_id}"

    def update(self, task, body_template):
        pass

    def delete(self, provider_ref):
        self.deleted.append(provider_ref)

    def get(self, provider_ref):
        return {"provider_ref": provider_ref}


class DummyRunner(Runner):
    async def run(self, agent, session, requests):
        return AgentReplyText(response="ok")

    async def stream(self, agent, session, requests):
        yield "ok"


class DummyAgent(Agent):
    def __init__(self, name: str = "planner"):
        super().__init__(name, DummyRunner("DummyRunner"))

    def get_description(self) -> str:
        return "Test agent"

    def get_a2a_card(self):
        return None

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


def _install_schedule_cfg(monkeypatch, schedule, multimodal_agents=None) -> None:
    """Point AKConfig at a config whose capabilities are scheduling and (optionally) multimodal."""

    class _Multimodal:
        enabled = multimodal_agents is not None
        agents = multimodal_agents

    class _Cfg:
        multimodal = _Multimodal
        sandbox = None

    _Cfg.schedule = schedule
    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))


@pytest.fixture
def manager(monkeypatch):
    """Serve the tools from a manager over the real in-memory store and a fake provider."""
    store = InMemoryScheduleStore()
    store.clear()
    instance = ScheduleManager(provider=RecordingScheduleProvider(), store=store)
    monkeypatch.setattr(ScheduleManager, "get", classmethod(lambda cls: instance))
    yield instance
    store.clear()


@pytest.fixture
def disabled(monkeypatch):
    """No 'schedule' block: the manager reports the capability as unconfigured."""
    monkeypatch.setattr(ScheduleManager, "get", classmethod(lambda cls: None))


@pytest.fixture
def acting_session():
    """A current session carrying an acting user, the way Runtime publishes it during a run."""
    session = Session("s1")
    session.get_volatile_cache().set(ACTING_USER_CACHE_KEY, "u1")
    token = Session.current_session.set(session)
    yield session
    Session.current_session.reset(token)


@pytest.fixture
def anonymous_session():
    """A current session whose run carried no user_id, so no acting user was published."""
    token = Session.current_session.set(Session("s1"))
    yield
    Session.current_session.reset(token)


@pytest.fixture
def registered_agent():
    """A registered agent, so a tool naming it passes the manager's named-agent precheck."""
    agent = DummyAgent()
    Runtime.current().register(agent)
    yield agent
    Runtime.current().deregister(agent)


def _create(manager: ScheduleManager, **overrides):
    fields = {"user_id": "u1", "prompt": "send the weekly report", "spec": ScheduleSpec(cron="0 9 * * 1"), "session_id": "s1"}
    fields.update(overrides)
    return manager.create(**fields)


class TestRegistration:
    def test_tools_registered_when_the_block_is_present(self, monkeypatch):
        _install_schedule_cfg(monkeypatch, _ScheduleConfig())

        assert [tool.name for tool in SystemToolFactory.get_all()] == SCHEDULE_TOOL_NAMES

    def test_tools_absent_without_the_block(self, monkeypatch):
        _install_schedule_cfg(monkeypatch, None)

        assert SystemToolFactory.get_all() == []

    def test_agents_list_restricts_tools_and_prompt(self, monkeypatch):
        _install_schedule_cfg(monkeypatch, _ScheduleConfig(agents=["planner"]))

        assert [tool.name for tool in SystemToolFactory.get_all("planner")] == SCHEDULE_TOOL_NAMES
        assert SystemToolFactory.get_all("triage") == []
        assert [tool.name for tool in SystemToolFactory.get_all()] == SCHEDULE_TOOL_NAMES  # anonymous: unfiltered

        assert "[Scheduling]" in SystemToolFactory.get_system_prompt_suffix("planner")
        assert SystemToolFactory.get_system_prompt_suffix("triage") == ""

    def test_agents_list_absent_keeps_all_agents(self, monkeypatch):
        _install_schedule_cfg(monkeypatch, _ScheduleConfig())

        assert [tool.name for tool in SystemToolFactory.get_all("anyone")] == SCHEDULE_TOOL_NAMES

    def test_each_capability_filters_on_its_own_agents_list(self, monkeypatch):
        _install_schedule_cfg(monkeypatch, _ScheduleConfig(agents=["planner"]), multimodal_agents=["vision"])

        assert [tool.name for tool in SystemToolFactory.get_all("planner")] == SCHEDULE_TOOL_NAMES
        assert [tool.name for tool in SystemToolFactory.get_all("vision")] == ["analyze_attachments"]
        assert SystemToolFactory.get_all("other") == []

    def test_system_prompt_suffix_carries_the_scheduling_guidance(self, monkeypatch):
        """The capability is self-describing: its whole section lands in the prompt suffix, with
        the empty per-tool descriptions leaving no blank lines behind."""
        _install_schedule_cfg(monkeypatch, _ScheduleConfig())

        suffix = SystemToolFactory.get_system_prompt_suffix()

        assert "[Scheduling]" in suffix
        for name in SCHEDULE_TOOL_NAMES:
            assert name in suffix
        assert "never invent one" in suffix
        assert "replaces every field rather than merging" in suffix
        assert '"error"' in suffix
        assert "" not in suffix.splitlines()

        _install_schedule_cfg(monkeypatch, None)
        assert SystemToolFactory.get_system_prompt_suffix() == ""

    def test_only_the_first_tool_carries_a_description(self, monkeypatch):
        _install_schedule_cfg(monkeypatch, _ScheduleConfig())

        tools = get_schedule_tools()

        assert tools[0].name == "create_schedule" and tools[0].description
        assert [tool.description for tool in tools[1:]] == ["", "", "", ""]


class TestDisabledCapability:
    @pytest.mark.asyncio
    async def test_every_tool_short_circuits(self, disabled, acting_session):
        results = [
            await create_schedule("send the weekly report", cron="0 9 * * 1"),
            await list_schedules(),
            await get_schedule("t1"),
            await update_schedule("t1", "send the daily report", cron="0 9 * * *"),
            await delete_schedule("t1"),
        ]

        assert {json.loads(result)["error"] for result in results} == {"scheduling capability is disabled"}


class TestActingUser:
    @pytest.mark.asyncio
    async def test_every_tool_requires_a_user_identity(self, manager, anonymous_session):
        results = [
            await create_schedule("send the weekly report", cron="0 9 * * 1"),
            await list_schedules(),
            await get_schedule("t1"),
            await update_schedule("t1", "send the daily report", cron="0 9 * * *"),
            await delete_schedule("t1"),
        ]

        for result in results:
            assert "requires a user identity" in json.loads(result)["error"]

    @pytest.mark.asyncio
    async def test_a_created_schedule_is_owned_by_the_acting_user(self, manager, acting_session):
        result = json.loads(await create_schedule("send the weekly report", cron="0 9 * * 1"))

        stored = manager.get_task(result["task_id"])
        assert stored.user_id == "u1"
        # The current session is the one occurrences run in (or derive their session ids from).
        assert stored.session_id == "s1"

    @pytest.mark.asyncio
    async def test_reads_and_mutations_cannot_reach_another_users_schedule(self, manager, acting_session):
        theirs = _create(manager, user_id="u2")

        assert "error" in json.loads(await get_schedule(theirs.task_id))
        assert "error" in json.loads(await update_schedule(theirs.task_id, "mine now", cron="0 9 * * *"))
        assert "error" in json.loads(await delete_schedule(theirs.task_id))
        assert manager.get_task(theirs.task_id).prompt == "send the weekly report"

    @pytest.mark.asyncio
    async def test_listing_is_scoped_to_the_acting_user(self, manager, acting_session):
        mine = _create(manager, user_id="u1")
        _create(manager, user_id="u2")

        listed = json.loads(await list_schedules())["schedules"]

        assert [task["task_id"] for task in listed] == [mine.task_id]


class TestToolContracts:
    @pytest.mark.asyncio
    async def test_create_returns_the_agent_facing_view(self, manager, acting_session, registered_agent):
        result = json.loads(await create_schedule("send the weekly report", cron="0 9 * * 1", timezone="Asia/Colombo", agent="planner"))

        assert result["prompt"] == "send the weekly report"
        assert result["cron"] == "0 9 * * 1"
        assert result["at"] is None
        assert result["timezone"] == "Asia/Colombo"
        assert result["session_mode"] == "reuse"
        assert result["agent"] == "planner"
        assert result["status"] == "active"
        assert result["trigger_count"] == 0
        # Provider machinery and ownership are not the agent's business.
        assert "provider_ref" not in result and "user_id" not in result

    @pytest.mark.asyncio
    async def test_create_reports_an_agent_that_is_not_registered(self, manager, acting_session):
        # The agent name comes from the model, so an invented one must fail here rather than at
        # every unattended fire time.
        result = json.loads(await create_schedule("send the weekly report", cron="0 9 * * 1", agent="not-an-agent"))

        assert result == {"error": "No agent available"}

    @pytest.mark.asyncio
    async def test_create_accepts_a_one_time_timestamp(self, manager, acting_session):
        result = json.loads(await create_schedule("send the report once", at=FUTURE_AT))

        assert result["at"] == FUTURE_AT
        assert result["cron"] is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "timing, message",
        [
            ({}, "exactly one of 'at'"),
            ({"cron": "0 9 * * 1", "at": FUTURE_AT}, "exactly one of 'at'"),
            ({"cron": "0 9 * *"}, "5-field expression"),
            ({"at": "2020-01-01T09:00:00"}, "must be in the future"),
            ({"cron": "0 9 * * 1", "timezone": "Mars/Olympus"}, "unknown schedule timezone"),
        ],
    )
    async def test_unusable_timing_is_reported_as_an_error(self, manager, acting_session, timing, message):
        result = json.loads(await create_schedule("send the weekly report", **timing))

        assert message in result["error"]

    @pytest.mark.asyncio
    async def test_get_reads_back_a_created_schedule(self, manager, acting_session):
        created = json.loads(await create_schedule("send the weekly report", cron="0 9 * * 1"))

        assert json.loads(await get_schedule(created["task_id"]))["task_id"] == created["task_id"]

    @pytest.mark.asyncio
    async def test_get_reports_an_unknown_schedule(self, manager, acting_session):
        assert "not found" in json.loads(await get_schedule("missing"))["error"]

    @pytest.mark.asyncio
    async def test_update_replaces_the_full_state(self, manager, acting_session):
        task = _create(manager)

        result = json.loads(await update_schedule(task.task_id, "send the daily report", at=FUTURE_AT, timezone="Asia/Colombo"))

        assert result["prompt"] == "send the daily report"
        assert result["at"] == FUTURE_AT
        assert result["cron"] is None  # replaced, not merged
        assert result["timezone"] == "Asia/Colombo"

    @pytest.mark.asyncio
    async def test_update_can_pause_and_resume(self, manager, acting_session):
        task = _create(manager)

        paused = json.loads(await update_schedule(task.task_id, task.prompt, cron="0 9 * * 1", status="paused"))
        assert paused["status"] == "paused"

        resumed = json.loads(await update_schedule(task.task_id, task.prompt, cron="0 9 * * 1", status="active"))
        assert resumed["status"] == "active"

    @pytest.mark.asyncio
    async def test_update_cannot_set_a_lifecycle_outcome(self, manager, acting_session):
        task = _create(manager)

        result = json.loads(await update_schedule(task.task_id, task.prompt, cron="0 9 * * 1", status="completed"))

        assert "can only be amended to one of" in result["error"]

    @pytest.mark.asyncio
    async def test_update_reports_an_unknown_schedule(self, manager, acting_session):
        assert "error" in json.loads(await update_schedule("missing", "send the daily report", cron="0 9 * * *"))

    @pytest.mark.asyncio
    async def test_delete_cancels_and_keeps_the_record(self, manager, acting_session):
        task = _create(manager)

        result = json.loads(await delete_schedule(task.task_id))

        assert result["status"] == ScheduleStatus.CANCELLED.value
        assert manager.get_task(task.task_id).status is ScheduleStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_delete_reports_an_unknown_schedule(self, manager, acting_session):
        assert "error" in json.loads(await delete_schedule("missing"))
