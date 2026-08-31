from __future__ import annotations

import asyncio
from types import SimpleNamespace

from demo import run_cli


class FakeRuntime:
    def agents(self):
        return {"orchestrator": object(), "intake": object()}


class FakeService:
    def __init__(self, *, delay: float = 0) -> None:
        self.agent = None
        self.runtime = FakeRuntime()
        self.delay = delay

    def select(self, name: str) -> None:
        self.agent = SimpleNamespace(name=name)

    async def run(self, prompt: str) -> str:
        await asyncio.sleep(self.delay)
        return f"reply: {prompt}"

    def new(self) -> None:
        pass

    def clear(self) -> None:
        pass


def input_sequence(*values: str):
    iterator = iter(values)
    return lambda _prompt: next(iterator)


def test_cli_shows_progress_before_reply() -> None:
    output: list[str] = []

    asyncio.run(
        run_cli(
            FakeService(),
            input_fn=input_sequence("hello", "!quit"),
            output=output.append,
            timeout_s=1,
        )
    )

    assert "Sarasavi Power is thinking... (usually 5-15 seconds)" in output
    assert "reply: hello" in output


def test_cli_reports_timeout_instead_of_waiting_forever() -> None:
    output: list[str] = []

    asyncio.run(
        run_cli(
            FakeService(delay=0.05),
            input_fn=input_sequence("hello", "!quit"),
            output=output.append,
            timeout_s=0.001,
        )
    )

    assert any("No response after" in line for line in output)
