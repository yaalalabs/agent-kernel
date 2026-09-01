import re
from dataclasses import dataclass

from .models import Objective

STOP = {
    "a",
    "an",
    "and",
    "apply",
    "calculate",
    "compare",
    "construct",
    "define",
    "describe",
    "discuss",
    "every",
    "explain",
    "for",
    "given",
    "how",
    "in",
    "is",
    "of",
    "prove",
    "show",
    "that",
    "the",
    "this",
    "to",
    "use",
    "why",
}
TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class CandidateSelection:
    objectives: list[Objective]
    mode: str
    exclusion_ids: list[str]
    keyword_ids: list[str]


def significant_terms(text: str) -> set[str]:
    return {token for token in TOKEN.findall(text.casefold()) if token not in STOP and len(token) > 1}


def select_candidates(question: str, objectives: list[Objective], semantic_scores=None, limit: int = 6) -> CandidateSelection:
    question_terms = significant_terms(question)
    overlap = {item.id: len(question_terms & significant_terms(item.text)) for item in objectives}
    exclusions = [item for item in objectives if item.kind == "excluded" and overlap[item.id] > 0]
    required = [item for item in objectives if item.kind == "required" and overlap[item.id] > 0]
    keyword_ids = [item.id for item in [*exclusions, *required]]
    if semantic_scores is not None:
        direct_ids = {item.id for item in required}
        remaining = [item for item in objectives if item.kind == "required" and item.id not in direct_ids]
        remaining.sort(key=lambda item: semantic_scores.get(item.id, -1), reverse=True)
        required.extend(item for item in remaining if semantic_scores.get(item.id, -1) >= 0.36)
    chosen = [*exclusions, *required[:limit]]
    mode = "semantic" if semantic_scores is not None else "lexical"
    return CandidateSelection(chosen, mode, [item.id for item in exclusions], keyword_ids)
