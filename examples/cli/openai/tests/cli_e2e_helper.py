# cli_e2e_helper.py
import sys

import pexpect


class CLITestHelper:
    def __init__(self, cli_path: str, timeout: int = 5):
        self.cli_path = cli_path
        self.timeout = timeout
        self.child = None

    def start(self):
        self.child = pexpect.spawn(sys.executable, [self.cli_path], encoding='utf-8', timeout=self.timeout)
        self.child.logfile = sys.stdout
        self.child.setecho(False)
        try:
            print("trying to read")
            readline = self.child.readline()
            print(readline)
        except Exception:
            pass

    def send_command(self, command: str):
        self.child.sendline(command)
        try:
            self.child.expect("(kernel)")
        except Exception:
            print("exception")
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
