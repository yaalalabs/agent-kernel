# test_cli.py
from pathlib import Path

from cli_e2e_helper import CLITestHelper

# def test_cli_interactive():
path = str((Path(__file__).resolve().parent / "../demo.py").resolve())
cli = CLITestHelper(cli_path=path,
                    prompt="AgentKernel CLI (type !help for commands or !quit to exit):")  # path to your CLI script
cli.start()

test_sequence = [
    ("greet Alice", "Hello, Alice!"),
    ("greet Bob", "Hello, Bob!"),
    ("!quit", "Unknown command"),
]

for cmd, expected in test_sequence:
    cli.send_command(cmd, expected)

cli.stop()
