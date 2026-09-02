# A bring-your-own AKEvaluator example for the CLI. This is a simple token-overlap evaluator that also demonstrates how to
# call an LLM judge directly via litellm (see llm_based_evaluation below).

import re

import litellm
from agentkernel.test.core.akevaluators import (
    AKEvaluationCase,
    AKEvaluationError,
    AKEvaluationResult,
    AKEvaluator,
    AKMissingInput,
)

_JUDGE_PROMPT = (
    "You are grading whether a chatbot's ACTUAL answer conveys the same information as the "
    "EXPECTED answer for the given QUESTION. Respond with only a single number between 0.0 and "
    "1.0 - no words, no explanation - where 1.0 means the answers fully agree and 0.0 means they "
    "do not agree at all.\n\n"
    "QUESTION: {question}\n"
    "EXPECTED: {expected}\n"
    "ACTUAL: {actual}\n\n"
    "Score:"
)

_SCORE_PATTERN = re.compile(r"([01](?:\.\d+)?)")


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


class TokenOverlapEvaluator(AKEvaluator):
    """score_based_evaluation: graded Jaccard token overlap (stdlib only, no LLM call).

    llm_based_evaluation: a single raw litellm.completion() call with a custom rubric prompt,
    parsed for a bare 0.0-1.0 score - no GEval, no schema-constrained JSON.
    """

    def score_based_evaluation(self, case: AKEvaluationCase) -> AKEvaluationResult:
        if not case.expected:
            raise AKMissingInput("score_based_evaluation requires AKEvaluationCase.expected")
        expected_tokens, actual_tokens = _tokens(case.expected), _tokens(case.actual)
        score = len(expected_tokens & actual_tokens) / len(expected_tokens | actual_tokens) if actual_tokens else 0.0
        return AKEvaluationResult(
            metric="jaccard_token_overlap",
            evaluator=self._config.evaluator,
            score=score,
            passed=score >= case.threshold,
        )

    def llm_based_evaluation(self, case: AKEvaluationCase) -> AKEvaluationResult:
        if not case.expected:
            raise AKMissingInput("llm_based_evaluation requires AKEvaluationCase.expected")
        llm = self._config.llm
        prompt = _JUDGE_PROMPT.format(question=case.user_input, expected=case.expected, actual=case.actual)
        try:
            response = litellm.completion(
                model=f"{llm.provider}/{llm.model}",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            content = response.choices[0].message.content.strip()
            match = _SCORE_PATTERN.search(content)
            if not match:
                raise ValueError(f"judge did not return a parseable score: {content!r}")
            score = max(0.0, min(1.0, float(match.group(1))))
        except Exception as exc:
            raise AKEvaluationError(f"custom llm-based evaluation failed: {exc}") from exc
        return AKEvaluationResult(
            metric="litellm_raw_judge",
            evaluator=self._config.evaluator,
            score=score,
            reason=content,
            passed=score >= case.threshold,
        )
