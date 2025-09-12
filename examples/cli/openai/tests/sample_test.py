# test_cli.py
from pathlib import Path

from cli_e2e_helper import CLITestHelper

# def test_cli_interactive():
path = str((Path(__file__).resolve().parent / "../demo.py").resolve())
cli = CLITestHelper(cli_path=path)  # path to your CLI script
cli.start()

test_sequence = [
    ("Hi", "Hello, Alice!"),
    ("Tell me weather", "Hello, Bob!"),
    ("!quit", "Unknown command"),
]

for cmd, expected in test_sequence:
    cli.send_command(cmd)

cli.stop()
