import asyncio
import re
import sys
from pathlib import Path


class Test:
    def __init__(self, path):
        working_dir = Path.cwd()
        self.path = working_dir / path
        self.proc = None

    _prompt_regex = re.compile(r"\((.+?)\) >> $")  # captures terminal prompt

    @staticmethod
    def _update_prompt(text: str):
        globals()["PROMPT"] = f"({text}) >> "

    @staticmethod
    def _get_prompt():
        return globals()["PROMPT"]

    async def _read_until_prompt(self):
        if self.proc is None:
            raise Exception("Process not started")
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

    async def send(self, message: str):
        print(f"{self._get_prompt()}{message}", flush=True)
        self.proc.stdin.write((message + "\n").encode('utf-8'))
        await self.proc.stdin.drain()

        output, prompt_text = await self._read_until_prompt()
        # Remove the prompt from the end
        response = self._prompt_regex.sub("", output).strip()
        print(response, flush=True)
        self._update_prompt(prompt_text)
        ansi_escape = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')
        return ansi_escape.sub('', response)

    async def stop(self):
        self.proc.stdin.close()
        await self.proc.wait()
