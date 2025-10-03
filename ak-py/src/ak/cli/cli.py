import asyncio
import logging
import readline  # Enables line editing and history features for input() in the CLI

from ..core import AgentService

# Configure logger only to print agent kernel logs
ak_logger = logging.getLogger("ak")
ak_logger.setLevel(logging.INFO)
ak_logger.propagate = False

if not ak_logger.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter('\033[36m(kernel) >> %(message)s\033[0m'))
    ak_logger.addHandler(handler)


class CLI:
    """
    CLI class provides a command-line interface for interacting with agents.
    """

    def __init__(self):
        self._service = AgentService()

    @staticmethod
    def _print(message: str = "", **kwargs):
        kwargs.setdefault('flush', True)
        print(message, **kwargs)

    def help(self):
        self._print("Available commands:")
        self._print("!h, !help - Show this help message")
        self._print("!ld, !load <module_name> - Load agent module")
        self._print("!ls, !list - List available agents")
        self._print("!n, !new - Start a new session")
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

    async def run(self):
        self._print("AgentKernel CLI (type !help for commands or !quit to exit):")
        self._service.select()

        if not self._service.agent:
            self._print("No agents available. Please load an agent module using !load <module_name>.")

        while True:
            name = self._service.agent.name if self._service.agent else "none"
            prompt = input(f"({name}) >> ")
            if not prompt.strip():
                continue
            if prompt.startswith("!"):
                tokens = prompt.lower().split()
                command = tokens[0]
                if command in ["!h", "!help"]:
                    self.help()
                elif command in ["!ls", "!list"]:
                    self.list()
                elif command in ["!ld", "!load"]:
                    if len(tokens) != 2:
                        self._print("Usage: !load <module_name>")
                        continue
                    session_id = self._service.session.id if self._service.session else None
                    self._service.load(name=tokens[1], session_id=session_id)
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
                self._print(f"\033[35m{await self._service.run(prompt=prompt)}\033[0m")
                self._print()
            else:
                self._print("No agent selected. Please select an agent using !select <agent_name>.")

    @classmethod
    def main(cls):
        try:
            cli = cls()
            asyncio.run(cli.run())
        except asyncio.CancelledError:
            cls._print()
