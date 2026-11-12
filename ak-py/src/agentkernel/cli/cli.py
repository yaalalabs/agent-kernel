import argparse
import asyncio
import logging
import os
import readline  # Enables line editing and history features for input() in the CLI
import threading

from ..core import AgentService
from ..core.model import AgentRequestText, Principal
from ..identity.errors import AuthenticationError
from ..identity.provider.base import RequestContext
from ..identity.provider.factory import IdentityProviderFactory

ak_cli_logger = logging.getLogger("ak.cli")

if not ak_cli_logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("\033[36m(kernel) >> %(message)s\033[0m"))
    ak_cli_logger.addHandler(handler)


class CLI:
    """
    CLI class provides a command-line interface for interacting with agents.
    """

    TOKEN_ENV = "AK_CLI_TOKEN"

    def __init__(self, token: str | None = None):
        """
        :param token: A credential for the configured identity provider; ``AK_CLI_TOKEN`` when omitted.
            Authenticated once when the REPL starts, and the resulting principal runs every prompt.
        """
        self._service = AgentService()
        self._token = token or os.environ.get(self.TOKEN_ENV)
        self._principal: Principal | None = None

    async def _authenticate(self) -> None:
        """Resolve the token once, before the first prompt.

        Without an identity block the token is ignored with a warning and the session runs as the
        anonymous principal, as every other surface does; a refused token exits with its reason,
        since a REPL nobody can use is worse than no REPL.

        :raises SystemExit: If the provider refuses the token.
        """
        if not self._token:
            return
        provider = IdentityProviderFactory.get()
        if provider is None:
            ak_cli_logger.warning("A token was given but no identity block is configured: running as the anonymous principal")
            return
        try:
            self._principal = await provider.authenticate(self._token, RequestContext(path="cli"))
        except AuthenticationError as e:
            raise SystemExit(f"Authentication failed: {e}") from e
        ak_cli_logger.info(f"Authenticated as {self._principal.subject}")

    @staticmethod
    def _print(message: str = "", **kwargs):
        kwargs.setdefault("flush", True)
        print(message, **kwargs)

    def help(self):
        self._print("Available commands:")
        self._print("!h, !help - Show this help message")
        self._print("!ld, !load <module_name> - Load agent module")
        self._print("!ls, !list - List available agents")
        self._print("!n, !new - Start a new session")
        self._print("!c, !clear - Clear the current session memory")
        self._print("!s, !select <agent_name> - Select an agent to run the prompt")
        self._print("!q, !quit - Exit the program")
        self._print()

    def list(self):
        agents = list(self._service.runtime.agents().values())
        if not agents:
            self._print("No agents available.")
        else:
            self._print("Available agents:")
            for agent in agents:
                self._print(f"  {agent.name}")
            self._print()

    @staticmethod
    async def _ainput(prompt: str) -> str:
        """
        Reads a line of input without blocking the event loop, so background tasks keep running between turns.
        The reader is a daemon thread, so Ctrl+C exits instead of waiting on a thread parked in `input()`.
        :param prompt: The prompt to display to the user.
        :return: The line entered by the user.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()

        def resolve(setter, value):
            if not future.done():
                setter(value)

        def read():
            try:
                line = input(prompt)
            except BaseException as e:  # noqa: BLE001 - relayed to the awaiting caller
                loop.call_soon_threadsafe(resolve, future.set_exception, e)
            else:
                loop.call_soon_threadsafe(resolve, future.set_result, line)

        threading.Thread(target=read, daemon=True, name="ak-cli-input").start()
        return await future

    async def run(self):
        await self._authenticate()
        self._print("AgentKernel CLI (type !help for commands or !quit to exit):")
        self._service.select()

        if not self._service.agent:
            self._print("No agents available. Please load an agent module using !load <module_name>.")

        while True:
            try:
                name = self._service.agent.name if self._service.agent else "none"
                prompt = await self._ainput(f"({name}) >> ")
                if not prompt.strip():
                    continue
                if prompt.startswith("!"):
                    tokens = prompt.split()
                    command = tokens[0].lower()  # only the command is case-insensitive; arguments are names
                    if command in ["!h", "!help"]:
                        self.help()
                    elif command in ["!c", "!clear"]:
                        self._service.clear()
                    elif command in ["!ld", "!load"]:
                        if len(tokens) != 2:
                            self._print("Usage: !load <module_name>")
                            continue
                        session_id = self._service.session.id if self._service.session else None
                        self._service.load(name=tokens[1], session_id=session_id)
                    elif command in ["!ls", "!list"]:
                        self.list()
                    elif command in ["!n", "!new"]:
                        self._service.new()
                    elif command in ["!q", "!quit"]:
                        break
                    elif command in ["!s", "!select"]:
                        if len(tokens) != 2:
                            self._print("Usage: !select <agent_name>")
                            continue
                        session_id = self._service.session.id if self._service.session else None
                        self._service.select(name=tokens[1], session_id=session_id)
                    else:
                        self._print("Unknown command. Type !help for available commands.")
                    continue

                if self._service.agent:
                    reply = await self._service.run_multi([AgentRequestText(prompt=prompt)], principal=self._principal)
                    self._print(f"\033[35m{reply}\033[0m")
                    self._print()
                else:
                    self._print("No agent selected. Please select an agent using !select <agent_name>.")
            except (KeyboardInterrupt, EOFError):
                raise
            except Exception as e:
                self._print(f"Error: {e}")
                ak_cli_logger.error("Exception in CLI run loop", exc_info=True)

    @classmethod
    def main(cls):
        # allow_abbrev=False: the CLI shares argv with the script that embeds it, whose own "--to x"
        # would otherwise be read as an abbreviated --token.
        parser = argparse.ArgumentParser(prog="agentkernel.cli", add_help=False, allow_abbrev=False)
        parser.add_argument(
            "--token",
            default=None,
            help=f"Credential for the configured identity provider; defaults to {cls.TOKEN_ENV}, which keeps it out of ps and shell history",
        )
        args, _ = parser.parse_known_args()
        try:
            cli = cls(token=args.token)
            asyncio.run(cli.run())
        except asyncio.CancelledError:
            cls._print()
