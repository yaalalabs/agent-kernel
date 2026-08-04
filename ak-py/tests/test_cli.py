import asyncio
import builtins
import sys
import threading

import pytest

from agentkernel.cli import cli as cli_module
from agentkernel.cli.cli import CLI


class ScriptedInput:
    """Stands in for builtins.input(): returns a fixed sequence of lines, then raises EOFError."""

    def __init__(self, lines: list[str]):
        self._lines = iter(lines)
        self.prompts: list[str] = []
        self.threads: list[threading.Thread] = []

    def __call__(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        self.threads.append(threading.current_thread())
        try:
            return next(self._lines)
        except StopIteration:
            raise EOFError("scripted input exhausted")


class StubAgent:
    def __init__(self, name: str):
        self.name = name


class StubSession:
    def __init__(self, id: str):
        self.id = id


class StubRuntime:
    def __init__(self, agents: dict[str, StubAgent]):
        self._agents = agents

    def agents(self) -> dict[str, StubAgent]:
        return self._agents


class StubService:
    """Stand-in for AgentService covering only the surface CLI.run() touches."""

    def __init__(self, agent_name: str | None = "demo"):
        self.agent = StubAgent(agent_name) if agent_name else None
        self.session = StubSession("session-1")
        self.runtime = StubRuntime({"demo": StubAgent("demo"), "other": StubAgent("other")})
        self.calls: list[tuple] = []
        self.reply = "the answer"
        self.error: Exception | None = None

    def select(self, session_id=None, name=None):
        self.calls.append(("select", name, session_id))

    def load(self, session_id, name):
        self.calls.append(("load", name, session_id))

    def new(self):
        self.calls.append(("new",))

    def clear(self):
        self.calls.append(("clear",))

    async def run(self, prompt: str) -> str:
        self.calls.append(("run", prompt))
        if self.error:
            raise self.error
        return self.reply


@pytest.fixture
def stub_service(monkeypatch):
    service = StubService()
    monkeypatch.setattr(cli_module, "AgentService", lambda: service)
    return service


class TestReadline:
    def test_cli_module_imports_readline(self):
        """readline is imported purely for its import-time side effect — dropping it silently
        removes arrow-key history and line editing from every interactive CLI session."""
        assert "readline" in sys.modules
        assert getattr(cli_module, "readline", None) is sys.modules["readline"]


class TestAinput:
    @pytest.mark.asyncio
    async def test_returns_the_typed_line_and_passes_the_prompt_through(self, monkeypatch):
        scripted = ScriptedInput(["hello"])
        monkeypatch.setattr(builtins, "input", scripted)

        assert await CLI._ainput("(demo) >> ") == "hello"
        assert scripted.prompts == ["(demo) >> "]

    @pytest.mark.asyncio
    async def test_reader_runs_on_a_named_daemon_thread(self, monkeypatch):
        scripted = ScriptedInput(["hello"])
        monkeypatch.setattr(builtins, "input", scripted)

        await CLI._ainput(">> ")

        reader = scripted.threads[0]
        assert reader is not threading.main_thread()
        assert reader.daemon is True
        assert reader.name == "ak-cli-input"

    @pytest.mark.asyncio
    async def test_does_not_block_the_event_loop(self, monkeypatch):
        released = threading.Event()

        def blocking_input(prompt: str = "") -> str:
            if not released.wait(5):
                raise AssertionError("event loop was blocked: the concurrent task never ran")
            return "typed"

        monkeypatch.setattr(builtins, "input", blocking_input)

        async def release():
            await asyncio.sleep(0.01)
            released.set()

        line, _ = await asyncio.gather(CLI._ainput(">> "), release())
        assert line == "typed"

    @pytest.mark.asyncio
    async def test_propagates_input_errors_to_the_caller(self, monkeypatch):
        def failing_input(prompt: str = "") -> str:
            raise EOFError("stdin closed")

        monkeypatch.setattr(builtins, "input", failing_input)

        with pytest.raises(EOFError, match="stdin closed"):
            await CLI._ainput(">> ")

    @pytest.mark.asyncio
    async def test_input_arriving_after_cancellation_is_discarded(self, monkeypatch):
        """The reader thread outlives a cancelled await; settling the already-cancelled future
        would raise InvalidStateError inside the loop callback."""
        released = threading.Event()

        def blocking_input(prompt: str = "") -> str:
            released.wait(5)
            return "late"

        monkeypatch.setattr(builtins, "input", blocking_input)

        errors: list[dict] = []
        asyncio.get_running_loop().set_exception_handler(lambda loop, context: errors.append(context))

        task = asyncio.create_task(CLI._ainput(">> "))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        released.set()
        await asyncio.sleep(0.05)  # let the reader thread hand its result back
        assert errors == []


class TestRunLoop:
    @pytest.mark.asyncio
    async def test_quit_command_exits_without_running_the_agent(self, stub_service, monkeypatch):
        monkeypatch.setattr(builtins, "input", ScriptedInput(["!quit"]))

        await CLI().run()

        assert not [call for call in stub_service.calls if call[0] == "run"]

    @pytest.mark.asyncio
    async def test_prompt_is_dispatched_to_the_agent_and_printed(self, stub_service, monkeypatch, capsys):
        scripted = ScriptedInput(["hello", "!q"])
        monkeypatch.setattr(builtins, "input", scripted)

        await CLI().run()

        assert ("run", "hello") in stub_service.calls
        assert "the answer" in capsys.readouterr().out
        assert scripted.prompts[0] == "(demo) >> "

    @pytest.mark.asyncio
    async def test_blank_input_is_ignored(self, stub_service, monkeypatch):
        monkeypatch.setattr(builtins, "input", ScriptedInput(["", "   ", "!q"]))

        await CLI().run()

        assert not [call for call in stub_service.calls if call[0] == "run"]

    @pytest.mark.asyncio
    async def test_commands_dispatch_to_the_service(self, stub_service, monkeypatch, capsys):
        monkeypatch.setattr(builtins, "input", ScriptedInput(["!ld demo", "!s other", "!n", "!c", "!ls", "!q"]))

        await CLI().run()

        assert ("load", "demo", "session-1") in stub_service.calls
        assert ("select", "other", "session-1") in stub_service.calls
        assert ("new",) in stub_service.calls
        assert ("clear",) in stub_service.calls
        assert "Available agents:" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_commands_with_wrong_arity_print_usage(self, stub_service, monkeypatch, capsys):
        monkeypatch.setattr(builtins, "input", ScriptedInput(["!ld", "!s", "!q"]))

        await CLI().run()

        out = capsys.readouterr().out
        assert "Usage: !load <module_name>" in out
        assert "Usage: !select <agent_name>" in out
        assert not [call for call in stub_service.calls if call[0] == "load"]

    @pytest.mark.asyncio
    async def test_unknown_command_is_reported(self, stub_service, monkeypatch, capsys):
        monkeypatch.setattr(builtins, "input", ScriptedInput(["!nope", "!q"]))

        await CLI().run()

        assert "Unknown command" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_agent_error_is_reported_and_the_loop_continues(self, stub_service, monkeypatch, capsys):
        stub_service.error = RuntimeError("boom")
        monkeypatch.setattr(builtins, "input", ScriptedInput(["first", "second", "!q"]))

        await CLI().run()

        assert ("run", "first") in stub_service.calls
        assert ("run", "second") in stub_service.calls
        assert capsys.readouterr().out.count("Error: boom") == 2

    @pytest.mark.asyncio
    async def test_eof_ends_the_loop(self, stub_service, monkeypatch):
        monkeypatch.setattr(builtins, "input", ScriptedInput([]))

        with pytest.raises(EOFError):
            await CLI().run()

    @pytest.mark.asyncio
    async def test_prompts_and_warns_when_no_agent_is_selected(self, monkeypatch, capsys):
        service = StubService(agent_name=None)
        monkeypatch.setattr(cli_module, "AgentService", lambda: service)
        scripted = ScriptedInput(["hello", "!q"])
        monkeypatch.setattr(builtins, "input", scripted)

        await CLI().run()

        out = capsys.readouterr().out
        assert "No agents available" in out
        assert "No agent selected" in out
        assert scripted.prompts[0] == "(none) >> "
