import asyncio
import re
import sys
from enum import StrEnum
from pathlib import Path
from typing import Any, Optional

from datasets import Dataset
from ragas import evaluate
from ragas.metrics import answer_relevancy, answer_similarity
from rapidfuzz import fuzz

from agentkernel.core.config import AKConfig


class Mode(StrEnum):
    FUZZY = "fuzzy"
    JUDGE = "judge"
    FALLBACK = "fallback"


class Test:
    _prompt_regex = re.compile(r"\((.+?)\) >> $")  # captures terminal prompt
    _prompt: str = ""
    _ragas_llm: Optional[Any] = None
    _ragas_embeddings: Optional[Any] = None

    def __init__(self, path, match_threshold=50, mode: Mode = None):
        """
        Initializes an instance of the Test with a specified command-line interface (CLI) path.
        :param path: Python file path as a string
        :param match_threshold: Fuzzy matching threshold for the response comparison.
        :param mode: Test comparison mode - 'fuzzy', 'judge', or 'fallback'. If None, uses config value.
        """
        working_dir = Path.cwd()
        self.path = working_dir / path
        self.proc = None
        self.last_agent_response = None
        self.last_user_input = ""
        self.match_threshold = match_threshold
        self.mode = AKConfig.get().test.mode if mode is None else mode

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
                output_str = output_bytes.decode("utf-8")
            except UnicodeDecodeError:
                continue  # wait for more bytes if multibyte char is incomplete

            # Search for prompt at the end
            match = self._prompt_regex.search(output_str[-30:])
            if match:
                captured_prompt_text = match.group(1)
                return output_str, captured_prompt_text

        return output_bytes.decode("utf-8"), captured_prompt_text

    async def start(self):
        """
        Starts the CLI to initialize the test
        """
        self.proc = await asyncio.create_subprocess_exec(
            sys.executable,
            self.path,
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
        self.last_user_input = message
        self.proc.stdin.write((message + "\n").encode("utf-8"))
        await self.proc.stdin.drain()

        output, prompt_text = await self._read_until_prompt()
        # Remove the prompt from the end
        response = self._prompt_regex.sub("", output).strip()
        print(response, flush=True)
        self._update_prompt(prompt_text)
        ansi_escape = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
        self.last_agent_response = ansi_escape.sub("", response)
        return self.last_agent_response

    @staticmethod
    def _fuzzy_compare(actual: str, expected: list[str], threshold: int = 50):
        """
        Compare an actual string against expected strings using fuzzy string matching.

        Uses fuzzy string matching to determine if the actual string is similar enough
        to any of the expected strings. The comparison passes if any expected string
        has a similarity score above the specified threshold.

        :param actual: The string to be compared.
        :param expected: A list of acceptable strings to compare against.
        :param threshold: The minimum similarity score (0-100) required for a match. Default is 50.
        :raises AssertionError: If the actual string doesn't match any expected string above the threshold score.
        :return: None - Returns implicitly when a match is found above the threshold.
        """
        if not expected:
            raise ValueError("Expected strings list cannot be empty for fuzzy comparison.")
        for item in expected:
            score = fuzz.ratio(actual, item)
            if score > threshold:
                return
        raise AssertionError(f"Response didn't pass the threshold score. Expected: {expected}, Received: {actual}")

    @staticmethod
    def _judge_compare(user_input: str, actual: str, expected: list[str] = None, threshold: float = 0.5):
        """
        Judge the model response using Ragas metrics.

        If one or more expected answers are provided, uses Ragas "answer_similarity"
        to compare the actual answer against each expected (ground truth). Passes if the
        similarity score with ANY expected is >= threshold.

        If no expected answers are provided, falls back to Ragas "answer_relevancy",
        which checks if the answer is relevant to the provided user_input (question).

        :param user_input: The user input string (question) used by Ragas.
        :param actual: The model answer to be evaluated.
        :param expected: A list of expected answers to be considered as ground truth.
        :param threshold: Minimum score in [0.0, 1.0] required to pass. Default is 0.5.
        :raises AssertionError: If no similarity/relevancy score meets the threshold.
        :return: None - Returns implicitly when the score is above the threshold.
        """
        # Initialize Ragas clients using LiteLLM lazily
        if Test._ragas_llm is None or Test._ragas_embeddings is None:
            from litellm import completion
            from ragas.embeddings import LiteLLMEmbeddings
            from ragas.llms import LiteLLMStructuredLLM

            judge_config = AKConfig.get().test.judge
            Test._ragas_llm = LiteLLMStructuredLLM(client=completion, model=judge_config.model, provider=judge_config.provider)
            Test._ragas_embeddings = LiteLLMEmbeddings(model=judge_config.embedding_model)

        llm = Test._ragas_llm
        embeddings = Test._ragas_embeddings

        if expected:
            # Try semantic similarity against each expected (ground truth). Pass if ANY meets threshold.
            for gt in expected:
                data = Dataset.from_dict(
                    {
                        "question": [user_input],
                        "answer": [actual],
                        "ground_truth": [gt],
                    }
                )
                result = evaluate(data, metrics=[answer_similarity], llm=llm, embeddings=embeddings)
                score = result["answer_similarity"][0]
                if score >= threshold:
                    return
            raise AssertionError(
                f"Response didn't pass judge answer_similarity against any expected. "
                f"Question: {user_input}\nAnswer: {actual}\nExpected: {expected}"
            )
        else:
            # No expected answers provided: use answer_relevancy which requires a user question
            if not user_input:
                raise AssertionError("user_input (question) is required for judge answer_relevancy metric")
            data = Dataset.from_dict(
                {
                    "question": [user_input],
                    "answer": [actual],
                }
            )
            result = evaluate(data, metrics=[answer_relevancy], llm=llm, embeddings=embeddings)
            score = result["answer_relevancy"][0]
            if score < threshold:
                raise AssertionError(
                    f"Response didn't pass judge answer_relevancy. Score: {score:.3f}, Threshold: {threshold:.3f}.\n"
                    f"Question: {user_input}\nAnswer: {actual}"
                )
            return

    @staticmethod
    def compare(actual: str, expected: list[str] = None, user_input: str = "", threshold: int = 50, mode: Mode = None):
        """
        Compare an actual string against a list of expected strings using the specified mode.

        Supports three comparison modes:
        - 'FUZZY': Only fuzzy string matching
        - 'JUDGE': LLM-based evaluation using Ragas (answer_similarity when expected answers are provided, otherwise answer_relevancy)
        - 'FALLBACK': Try fuzzy first, fallback to LLM evaluation if fuzzy fails

        :param actual: The string to be compared.
        :param expected: A list of acceptable strings to compare against.
        :param user_input: The user input string (question). Used for LLM evaluation.
        :param threshold: The minimum similarity score (0-100) is required for a fuzzy match. Default is 50.
        :param mode: Comparison mode - 'fuzzy', 'judge', or 'fallback'. Default is 'fallback'.
        :raises AssertionError: If the actual string doesn't match any expected string.
        :return: None - Returns implicitly when a match is found.
        """
        # Validate mode
        if mode not in [Mode.FUZZY, Mode.JUDGE, Mode.FALLBACK, None]:
            raise ValueError(f"Invalid mode: {mode}. Must be one of: {Mode.FUZZY}, {Mode.JUDGE}, {Mode.FALLBACK}")

        # preference order: mode arg > config > fallback
        if mode:
            selected_mode = mode
        else:
            selected_mode = AKConfig.get().test.mode
            if not selected_mode:
                selected_mode = Mode.FALLBACK

        if selected_mode == Mode.JUDGE:
            Test._judge_compare(user_input=user_input, actual=actual, expected=expected, threshold=threshold / 100)
        elif selected_mode == Mode.FUZZY:
            Test._fuzzy_compare(actual=actual, expected=expected, threshold=threshold)
        elif selected_mode == Mode.FALLBACK:
            # Try fuzzy first, fallback to judge if fuzzy fails
            try:
                Test._fuzzy_compare(actual=actual, expected=expected, threshold=threshold)
            except AssertionError:
                try:
                    Test._judge_compare(user_input=user_input, actual=actual, expected=expected, threshold=threshold / 100)
                except AssertionError:
                    raise AssertionError(f"Response didn't pass fuzzy matching or judge evaluation. Expected: {expected}, Received: {actual}")

    async def expect(self, expected: list[str]):
        """
        Asserts that the last response received from the CLI matches the expected message.
        Uses the mode specified during Test initialization.
        :param expected: The expected message variants.
        """
        if self.last_agent_response is None:
            raise AssertionError("No response available to compare. Ensure send() was called before expect().")
        self.compare(
            actual=self.last_agent_response,
            expected=expected,
            user_input=self.last_user_input,
            threshold=self.match_threshold,
            mode=self.mode,
        )

    async def stop(self):
        """
        Stops the CLI.
        """
        self.proc.stdin.close()
        await self.proc.wait()


Test.__test__ = False  # pytest tries to run Test as a test without the flag
