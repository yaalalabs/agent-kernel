import asyncio
import re
import sys
from pathlib import Path

from rapidfuzz import fuzz


class Test:
    _prompt_regex = re.compile(r"\((.+?)\) >> $")  # captures terminal prompt
    _prompt = ""

    def __init__(self, path, match_threshold=50):
        """
        Initializes an instance of the Test with a specified command-line interface (CLI) path.
        :param path: Python file path as a string
        :param match_threshold: Fuzzy matching threshold for the response comparison.
        """
        working_dir = Path.cwd()
        self.path = working_dir / path
        self.proc = None
        self.latest = None
        self.match_threshold = match_threshold

    @classmethod
    def _update_prompt(cls, text: str):
        """
        Updates the global prompt string.
        :param text: The text to be inserted into the global prompt.
        """
        cls._prompt = f"({text}) >> "

    @classmethod
    def _get_prompt(cls):
        """
        Returns the global prompt string.
        """
        return cls._prompt

    async def _read_until_prompt(self):
        """
        Reads from the subprocess stdout until the prompt is found.
        """
        if self.proc is None:
            raise RuntimeError("Process not started")
        output_bytes = b""
        captured_prompt_text = None

        while True:
            chunk = await self.proc.stdout.read(1024)
            if not chunk:
                break
            output_bytes += chunk
            try:
                output_str = output_bytes.decode('utf-8')
            except UnicodeDecodeError:
                continue  # wait for more bytes if multibyte char is incomplete

            # Search for prompt at the end
            match = self._prompt_regex.search(output_str[-30:])
            if match:
                captured_prompt_text = match.group(1)
                return output_str, captured_prompt_text

        return output_bytes.decode('utf-8'), captured_prompt_text

    async def start(self):
        """
        Starts the CLI to initialize the test
        """
        self.proc = await asyncio.create_subprocess_exec(
            sys.executable, self.path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # merge stderr into stdout
        )

        # Capture the initial welcome message and prompt
        welcome, prompt_text = await self._read_until_prompt()
        welcome_stripped = self._prompt_regex.sub("", welcome).strip()
        print(welcome_stripped, flush=True)
        self._update_prompt(prompt_text)

    async def send(self, message: str) -> str:
        """
        Sends a message to the CLI and returns the response.
        :param message: The message to be sent to the CLI.
        :return: The response from the subprocess.
        """
        print(f"{self._get_prompt()}{message}", flush=True)
        self.proc.stdin.write((message + "\n").encode('utf-8'))
        await self.proc.stdin.drain()

        output, prompt_text = await self._read_until_prompt()
        # Remove the prompt from the end
        response = self._prompt_regex.sub("", output).strip()
        print(response, flush=True)
        self._update_prompt(prompt_text)
        ansi_escape = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')
        self.latest = ansi_escape.sub('', response)
        return self.latest

    @staticmethod
    def compare(actual: str, expected: str, threshold: int = 50):
        score = fuzz.ratio(actual, expected)
        assert score > threshold, f"Response didn't pass the threshold score. Expected: {expected}, Received: {actual}"

    async def expect(self, expected: str):
        """
        Asserts that the last response received from the CLI matches the expected message (fuzzy).
        :param expected: The expected message.
        """
        if self.latest is None:
            raise AssertionError("No response available to compare. Ensure send() was called before expect().")
        self.compare(self.latest, expected, self.match_threshold)

    async def stop(self):
        """
        Stops the CLI.
        """
        self.proc.stdin.close()
        await self.proc.wait()


Test.__test__ = False  # pytest tries to run Test as a test without the flag
