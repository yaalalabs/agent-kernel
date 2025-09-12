# cli_e2e_helper.py
import sys

import pexpect


class CLITestHelper:
    def __init__(self, cli_path: str, prompt: str = ">>> ", timeout: int = 5):
        self.cli_path = cli_path
        self.prompt = prompt
        self.timeout = timeout
        self.child = None

    def start(self):
        self.child = pexpect.spawn(sys.executable, [self.cli_path], encoding='utf-8', timeout=self.timeout)
        self.child.logfile = sys.stdout
        self.child.setecho(False)
        try:
            self.child.readline()
        except Exception:
            pass
        # self.child.expect(self.prompt)

    def send_command(self, command: str, expected_output: str = None):
        self.child.sendline(command)
        if expected_output is not None:
            try:
                self.child.expect(expected_output)
            except Exception:
                pass
        if self.prompt:
            try:
                self.child.expect(self.prompt)
            except Exception:
                pass

    def stop(self):
        if self.child.isalive():
            self.child.sendline("!quit")
            try:
                self.child.expect(pexpect.EOF)
            except Exception:
                pass
            self.child.close()
        else:
            pass
