import argparse
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx


class TrafficSimulator:
    """Sends a fixed set of questions to the agent under one session id, so its traces can be graded."""

    QUESTIONS = (
        "Where is my order A-1001?",  # hand-off + tool call
        "Can you check order A-9999 for me?",  # tool returns "not found"
        "Write me a poem about the ocean.",  # off-topic: should decline, no tool
    )
    MAX_ATTEMPTS = 3
    TIMEOUT = 30.0
    RETRY_WAIT = 5.0
    # Only failures that mean the request never reached the agent. A 504 or a read timeout is not retried: the
    # request may already be queued, and sending it again would run the agent twice and leave an extra trace.
    RETRY_STATUSES = frozenset({429, 502, 503})
    WARM_UP_QUESTION = "Hello"

    def __init__(self, chat_url: str, session_id: str | None = None, transport: httpx.BaseTransport | None = None):
        self._chat_url = chat_url
        self._session_id = session_id or str(uuid.uuid4())
        self._transport = transport

    @property
    def session_id(self) -> str:
        """The session id every request is sent under."""
        return self._session_id

    def send_questions(self) -> list[str]:
        """Sends each question as its own request (so its own trace) and returns the replies in order."""
        with httpx.Client(timeout=self.TIMEOUT, transport=self._transport) as client:
            return [self._send_question(client, question) for question in self.QUESTIONS]

    def warm_up(self) -> None:
        """Sends one question under a throwaway session, so cold starts hit it rather than the graded requests.

        Its reply and any failure are ignored: a cold start can make it time out at the gateway while its queued
        run still finishes.
        """
        payload = {"prompt": self.WARM_UP_QUESTION, "session_id": f"warm-up-{uuid.uuid4()}", "agent": "triage"}
        with httpx.Client(timeout=self.TIMEOUT, transport=self._transport) as client:
            try:
                client.post(self._chat_url, json=payload)
            except httpx.HTTPError:
                pass

    def _send_question(self, client: httpx.Client, question: str) -> str:
        """Posts one question to /chat, retrying only failures that never reached the agent, and returns the reply."""
        payload = {"prompt": question, "session_id": self._session_id, "agent": "triage"}
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                response = client.post(self._chat_url, json=payload)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                if attempt == self.MAX_ATTEMPTS:
                    raise
                time.sleep(self.RETRY_WAIT)
                continue
            if response.status_code not in self.RETRY_STATUSES or attempt == self.MAX_ATTEMPTS:
                break
            time.sleep(self.RETRY_WAIT)
        response.raise_for_status()
        return response.json().get("result", "")

    @classmethod
    def chat_url_from_env(cls, deploy_dir: Path) -> str:
        """Reads the /chat URL from ``AK_TEST_ENDPOINT``, or the ``agent_invoke_url`` Terraform output of ``deploy_dir``."""
        if url := os.getenv("AK_TEST_ENDPOINT"):
            return url
        try:
            result = subprocess.run(
                ["terraform", f"-chdir={deploy_dir}", "output", "-raw", "agent_invoke_url"],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as e:
            raise RuntimeError(f"could not read agent_invoke_url from {deploy_dir}: {e}") from e
        if not (url := result.stdout.strip()):
            raise RuntimeError(f"agent_invoke_url output in {deploy_dir} is empty; deploy the example first")
        return url

    @classmethod
    def cli(cls, argv: list[str] | None = None) -> int:
        """Sends the questions from the command line and prints each reply and the session id."""
        parser = argparse.ArgumentParser(description="Send the example's questions to the deployed agent.")
        parser.add_argument("--endpoint", help="the agent's /chat URL (default: AK_TEST_ENDPOINT or terraform output)")
        parser.add_argument("--session-id", help="session id for every request (default: a new uuid4)")
        args = parser.parse_args(argv)

        chat_url = args.endpoint or cls.chat_url_from_env(Path(__file__).parent / "deploy")
        simulator = cls(chat_url, session_id=args.session_id)
        for question, reply in zip(cls.QUESTIONS, simulator.send_questions()):
            print(f"> {question}\n{reply}\n")
        print(f"session id: {simulator.session_id}")
        return 0


if __name__ == "__main__":
    sys.exit(TrafficSimulator.cli())
