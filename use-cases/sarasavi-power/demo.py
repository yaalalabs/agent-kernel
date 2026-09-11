"""Local Agent Kernel terminal client; WhatsApp credentials are not required.

Unlike Agent Kernel's stock CLI loop, this wrapper prints progress immediately
after each prompt and applies a bounded response timeout. The underlying
``AgentService``, agents, sessions, tools, agent transfers, and hooks are unchanged.

Run:  python demo.py     (or: uv run python demo.py)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable

# Load .env before importing agent.py, which reads the configured model.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from agentkernel.adk import GoogleADKModule
from agentkernel.core import AgentService

from agent import AGENTS
from hooks import register_hooks
from localization import configure_utf8_console
from startup import require_gemini_config

module = GoogleADKModule(AGENTS)
register_hooks(module, AGENTS)
logger = logging.getLogger("sarasavi.cli")


def _print(message: str = "") -> None:
    print(message, flush=True)


def _response_timeout() -> float:
    raw = os.environ.get("SARASAVI_RESPONSE_TIMEOUT", "60")
    try:
        timeout = float(raw)
    except ValueError:
        return 60.0
    return timeout if 5 <= timeout <= 300 else 60.0


def _help(output: Callable[[str], None]) -> None:
    output("Commands: !help, !list, !new, !clear, !select <agent>, !quit")


async def run_cli(
    service: AgentService | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    output: Callable[[str], None] = _print,
    timeout_s: float | None = None,
) -> None:
    """Run the judge-friendly terminal loop around Agent Kernel AgentService."""
    service = service or AgentService()
    timeout_s = _response_timeout() if timeout_s is None else timeout_s
    service.select(name="orchestrator")

    output("AgentKernel CLI (type !help for commands or !quit to exit):")
    while True:
        name = service.agent.name if service.agent else "none"
        try:
            prompt = input_fn(f"({name}) >> ")
        except (EOFError, KeyboardInterrupt):
            output("")
            return

        prompt = prompt.strip()
        if not prompt:
            continue
        if prompt.startswith("!"):
            tokens = prompt.lower().split()
            command = tokens[0]
            if command in ("!q", "!quit"):
                return
            if command in ("!h", "!help"):
                _help(output)
            elif command in ("!ls", "!list"):
                names = ", ".join(service.runtime.agents()) or "none"
                output(f"Available agents: {names}")
            elif command in ("!n", "!new"):
                service.new()
                output("Started a new session.")
            elif command in ("!c", "!clear"):
                service.clear()
                output("Cleared the current session.")
            elif command in ("!s", "!select") and len(tokens) == 2:
                service.select(name=tokens[1])
                selected = service.agent.name if service.agent else "none"
                output(f"Selected agent: {selected}")
            else:
                output("Unknown command. Type !help for available commands.")
            continue

        if not service.agent:
            output("No agent selected. Use !select orchestrator.")
            continue

        output("Sarasavi Power is thinking... (usually 5-15 seconds)")
        started = time.monotonic()
        logger.info("Agent request started: agent=%s timeout_s=%s", service.agent.name, timeout_s)
        try:
            reply = await asyncio.wait_for(service.run(prompt=prompt), timeout=timeout_s)
        except TimeoutError:
            logger.warning("Agent request timed out after %.2f seconds", time.monotonic() - started)
            output(
                f"No response after {timeout_s:g} seconds. Check your connection and try again; "
                "set SARASAVI_RESPONSE_TIMEOUT to increase this limit."
            )
        except Exception as exc:
            logger.exception("Agent request failed after %.2f seconds", time.monotonic() - started)
            output(f"Request failed: {exc}")
        else:
            logger.info("Agent request completed in %.2f seconds", time.monotonic() - started)
            output(reply)
        output("")


if __name__ == "__main__":
    configure_utf8_console()
    model = require_gemini_config()
    _print(f"Sarasavi Power CLI - model: {model}")
    asyncio.run(run_cli())
