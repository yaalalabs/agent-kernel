import asyncio
import re
import sys
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import ClassVar

from agentkernel.core.util.factory import AKConfigError, require_extra, resolve_dotted

from .config import AKTestConfig
from .core.akevaluators import AKEvaluationCase, AKEvaluationResult, AKEvaluator

_BUILTIN_EVALUATORS = ["deepeval"]


class Mode(StrEnum):
    SCORE = "score"
    LLM = "llm"
    FALLBACK = "fallback"


class Test:
    _prompt_regex = re.compile(r"\((.+?)\) >> $")  # captures terminal prompt
    _prompt: str = ""

    _evaluator: ClassVar[tuple[str, AKEvaluator] | None] = None
    _evaluator_lock: ClassVar[RLock] = RLock()

    def __init__(self, path, match_threshold: float = 0.5, mode: Mode = None):
        """
        Initializes an instance of the Test with a specified command-line interface (CLI) path.
        :param path: Python file path as a string
        :param match_threshold: Matching threshold in [0.0, 1.0] for the response comparison.
        :param mode: Test comparison mode - 'score', 'llm', or 'fallback'. If None, uses config value.
        """
        working_dir = Path.cwd()
        self.path = working_dir / path
        self.proc = None
        self.last_agent_response = None
        self.last_user_input = ""
        self.match_threshold = match_threshold
        self.mode = AKTestConfig.get().mode if mode is None else mode
        self._stderr_task = None

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
            # Keep stderr separate: agent responses are stdout-only, while log output
            # (AK loggers write to stderr) would otherwise pollute captured responses
            # and break comparisons. It is drained in the background for diagnostics.
            stderr=asyncio.subprocess.PIPE,
        )
        self._stderr_task = asyncio.get_running_loop().create_task(self._drain_stderr())

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

    @classmethod
    def _resolve_evaluator(cls) -> AKEvaluator:
        configured = AKTestConfig.get().evaluator
        cached = cls._evaluator
        if cached is not None and cached[0] == configured:
            return cached[1]
        with cls._evaluator_lock:
            cached = cls._evaluator
            if cached is not None and cached[0] == configured:
                return cached[1]
            evaluator_cls = cls._resolve_evaluator_class(configured)
            instance = evaluator_cls(AKTestConfig.get())
            cls._evaluator = (configured, instance)
            return instance

    @classmethod
    def _resolve_evaluator_class(cls, configured: str) -> type[AKEvaluator]:
        if configured == "deepeval":
            with require_extra("test", "evaluator: deepeval"):
                from .core.akevaluators.deepeval import DeepevalAKEvaluator
            return DeepevalAKEvaluator
        if "." not in configured:
            raise AKConfigError(
                f"unknown evaluator '{configured}'; expected one of {_BUILTIN_EVALUATORS} or a dotted path to an AKEvaluator subclass"
            )
        return resolve_dotted(configured, base=AKEvaluator)

    @classmethod
    def _reset_evaluator(cls) -> None:
        cls._evaluator = None

    @staticmethod
    def compare(
        actual: str,
        expected: list[str] = None,
        user_input: str = "",
        threshold: float = 0.5,
        mode: Mode = None,
        return_metrics: bool = False,
    ) -> AKEvaluationResult | None:
        """
        Compare an actual string against a list of expected strings using the specified mode.

        Supports three comparison modes:
        - 'SCORE': Deterministic scoring via the configured evaluator's score_based_evaluation
        - 'LLM': LLM-as-judge scoring via the configured evaluator's llm_based_evaluation
        - 'FALLBACK': Try score first, fall back to llm evaluation if score fails

        :param actual: The string to be compared.
        :param expected: A list of acceptable strings to compare against.
        :param user_input: The user input string (question). Used for LLM evaluation.
        :param threshold: The minimum score in [0.0, 1.0] required to pass. Default is 0.5.
        :param mode: Comparison mode - 'score', 'llm', or 'fallback'. Default is 'fallback'.
        :param return_metrics: If True, return the decisive AKEvaluationResult instead of raising on failure.
        :raises AssertionError: If the actual string doesn't match any expected string and return_metrics is False.
        :return: The decisive AKEvaluationResult if return_metrics is True, else None.
        """
        if mode is not None and mode not in (Mode.SCORE, Mode.LLM, Mode.FALLBACK):
            raise ValueError(f"Invalid mode: {mode}. Must be one of: {Mode.SCORE}, {Mode.LLM}, {Mode.FALLBACK}")
        if not expected:
            raise ValueError("Expected strings list cannot be empty for comparison.")

        selected_mode = mode or Mode(AKTestConfig.get().mode)
        evaluator = Test._resolve_evaluator()

        attempts: list[AKEvaluationResult] = []
        decisive: AKEvaluationResult | None = None

        for exp in expected:
            case = AKEvaluationCase(user_input=user_input, actual=actual, expected=exp)

            if selected_mode == Mode.SCORE:
                result, result_mode = evaluator.score_based_evaluation(case), Mode.SCORE
            elif selected_mode == Mode.LLM:
                result, result_mode = evaluator.llm_based_evaluation(case), Mode.LLM
            else:  # FALLBACK
                score_result = evaluator.score_based_evaluation(case)
                if score_result.score is not None and score_result.score >= threshold:
                    result, result_mode = score_result, Mode.SCORE
                else:
                    attempts.append(Test._stamp(score_result, Mode.SCORE, threshold, exp))
                    result, result_mode = evaluator.llm_based_evaluation(case), Mode.LLM

            stamped = Test._stamp(result, result_mode, threshold, exp)
            if stamped.passed:
                decisive = stamped
                decisive.attempts = attempts
                break
            attempts.append(stamped)
            decisive = stamped  # stands as decisive unless a later alternative passes

        if not decisive.passed:
            decisive.attempts = attempts[:-1]  # every non-decisive attempt, decisive excluded
            message = Test._failure_message(selected_mode, expected, actual)
            if return_metrics:
                return decisive
            raise AssertionError(message)

        return decisive if return_metrics else None

    @staticmethod
    def _stamp(result: AKEvaluationResult, mode: Mode, threshold: float, expected: str) -> AKEvaluationResult:
        result.mode = mode.value
        result.threshold = threshold
        result.expected = expected
        result.passed = result.score is not None and result.score >= threshold
        return result

    @staticmethod
    def _failure_message(mode: Mode, expected: list[str], actual: str) -> str:
        if mode == Mode.SCORE:
            return f"Response didn't pass the score threshold. Expected: {expected}, Received: {actual}"
        if mode == Mode.LLM:
            return f"Response didn't pass llm evaluation against any expected. Expected: {expected}, Received: {actual}"
        return f"Response didn't pass score matching or llm evaluation. Expected: {expected}, Received: {actual}"

    async def expect(self, expected: list[str], return_metrics: bool = False) -> AKEvaluationResult | None:
        """
        Asserts that the last response received from the CLI matches the expected message.
        Uses the mode specified during Test initialization.
        :param expected: The expected message variants.
        :param return_metrics: If True, return the decisive AKEvaluationResult instead of raising on failure.
        """
        if self.last_agent_response is None:
            raise AssertionError("No response available to compare. Ensure send() was called before expect().")
        return self.compare(
            actual=self.last_agent_response,
            expected=expected,
            user_input=self.last_user_input,
            threshold=self.match_threshold,
            mode=self.mode,
            return_metrics=return_metrics,
        )

    async def _drain_stderr(self):
        """
        Continuously drains the CLI's stderr (log output), echoing each line to the test
        runner's stderr. Keeps the pipe from filling (which would block the subprocess)
        while keeping logs out of the captured agent responses.
        """
        while True:
            line = await self.proc.stderr.readline()
            if not line:
                break
            print(line.decode("utf-8", errors="replace").rstrip(), file=sys.stderr, flush=True)

    async def stop(self):
        """
        Stops the CLI.
        """
        self.proc.stdin.close()
        await self.proc.wait()
        if self._stderr_task is not None:
            await self._stderr_task  # finishes on stderr EOF once the process exits
            self._stderr_task = None


Test.__test__ = False  # pytest tries to run Test as a test without the flag
