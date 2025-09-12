import asyncio
import re
import sys

commands = ["History of Sri Lanka", "Tell me more", "!select math", "!new", "!quit"]

# Regex with a capture group for the dynamic part of the prompt
PROMPT_REGEX = re.compile(r"\((.+?)\) >> $")


def update_prompt(text):
    globals()["PROMPT"] = f"({text}) >> "


def get_prompt():
    return globals()["PROMPT"]


async def run_cli_e2e(cli_file: str, commands: list, prompt_regex: re.Pattern = PROMPT_REGEX):
    # Merge stderr into stdout so logging outputs are captured
    proc = await asyncio.create_subprocess_exec(
        sys.executable, cli_file,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,  # merge stderr into stdout
    )

    async def read_until_prompt():
        """Read stdout until the next prompt appears, handling full Unicode and regex prompt."""
        output_bytes = b""
        captured_prompt_text = None

        while True:
            chunk = await proc.stdout.read(1024)
            if not chunk:
                break
            output_bytes += chunk

            try:
                output_str = output_bytes.decode('utf-8')
            except UnicodeDecodeError:
                continue  # wait for more bytes if multi-byte char is incomplete

            # Search for prompt at the end
            match = prompt_regex.search(output_str[-30:])
            if match:
                captured_prompt_text = match.group(1)
                return output_str, captured_prompt_text

        return output_bytes.decode('utf-8'), captured_prompt_text

    # Capture initial welcome message and prompt
    welcome, prompt_text = await read_until_prompt()
    welcome_stripped = prompt_regex.sub("", welcome).strip()
    print(welcome_stripped, flush=True)
    update_prompt(prompt_text)

    responses = []

    for cmd in commands:
        print(f"{get_prompt()}{cmd}", flush=True)
        proc.stdin.write((cmd + "\n").encode('utf-8'))
        await proc.stdin.drain()

        output, prompt_text = await read_until_prompt()
        # Remove the prompt from the end
        response = prompt_regex.sub("", output).strip()
        print(response, flush=True)
        update_prompt(prompt_text)

        # Remove ANSI escape sequences
        ansi_escape = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')
        responses.append(ansi_escape.sub('', response))

    proc.stdin.close()
    await proc.wait()

    i = 0
    for response in responses:
        print(f"{i + 1}-[{commands[i]}]-{response}", flush=True)
        i += 1


if __name__ == "__main__":
    asyncio.run(run_cli_e2e("../demo.py", commands))
