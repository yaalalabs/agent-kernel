import asyncio
import readline  # Enables line editing and history features for input() in the CLI

from uuid import uuid4

from ..core import Runtime, Session


class CLI:
    """
    CLI class provides a command-line interface for interacting with agents.
    """

    def __init__(self):
        """
        Initializes the CLI instance.
        """
        self._agent = None
        self._runtime = Runtime.instance()
        self._session = None

    def select(self, name: str | None = None):
        """
        Selects an agent by name, or the first available agent if no name is provided.
        """
        if name:
            selected = self._runtime.agents().get(name)
            if selected:
                self._agent = selected
            else:
                print(f"No agent found with name '{name}'")
        else:
            agents = list(self._runtime.agents().values())
            self._agent = agents[0] if agents else None
            if self._session is None and self._agent is not None:
                self.new()

    def help(self):
        print("Available commands:")
        print("!h, !help - Show this help message")
        print("!ld, !load <module_name> - Load agent module")
        print("!ls, !list - List available agents")
        print("!n, !new - Start a new session")
        print("!s, !select <agent_name> - Select an agent to run the prompt") 
        print("!q, !quit - Exit the program")
        print()

    def new(self):
        if self._agent:
            self._session = self._runtime.sessions().load(str(uuid4()))
            print(f"Starting new session: {self._session.id}")
        else:
            print("No agent selected. Please select an agent using !select <agent_name>.")

    def list(self):
        agents = list(self._runtime.agents().values())
        if not agents:
            print("No agents available.")
        else:
            print("Available agents:")
            for agent in agents:
                print(f"  {agent.name}")
            print()

    def load(self, name: str):
        """
        Loads an agent module by name.
        """
        try:
            self._runtime.load(name)
            if not self._agent:
                self.select()
        except ImportError as e:
            print(f"No module found with name '{name}': {e}")
            return None

    async def run(self):
        print("AgentKernel CLI (type !help for commands or !quit to exit):")
        self.select()

        if not self._agent:
            print("No agents available. Please load an agent module using !load <module_name>.")

        while True:
            name = self._agent.name if self._agent else "none"
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
                        print("Usage: !load <module_name>")
                        continue
                    self.load(tokens[1])
                elif command in ["!n", "!new"]:
                    self.new()
                elif command in ["!q", "!quit"]:
                    break
                elif command in ["!s", "!select"]:
                    if len(tokens) != 2:
                        print("Usage: !select <agent_name>")
                        continue
                    self.select(tokens[1])
                else:
                    print("Unknown command. Type !help for available commands.")
                continue

            if self._agent:
                print(await self._runtime.run(self._agent, self._session, prompt))
                print()
            else:
                print("No agent selected. Please select an agent using !select <agent_name>.")

    @staticmethod
    def main():
        try:
            cli = CLI()
            asyncio.run(cli.run())
        except asyncio.CancelledError:
            print()


if __name__ == "__main__":
    CLI.main()
