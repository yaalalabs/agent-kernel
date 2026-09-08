from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(StrictModel):
    document_id: str = Field(min_length=1, max_length=100)
    page: int = Field(ge=1, le=80)
    quote: str = Field(min_length=8, max_length=1600)


class Objective(StrictModel):
    id: str = ""
    text: str = Field(min_length=5, max_length=1800)
    kind: Literal["required", "excluded"] = "required"
    evidence: Evidence
    approved: bool = False


class Question(StrictModel):
    id: str = ""
    text: str = Field(min_length=5, max_length=5000)
    label: str = Field(default="", max_length=80)
    evidence: Evidence
    approved: bool = False


class Extraction(StrictModel):
    objectives: list[Objective] = Field(default_factory=list, max_length=30)
    questions: list[Question] = Field(default_factory=list, max_length=50)


class Match(StrictModel):
    question_id: str
    objective_ids: list[str] = Field(default_factory=list, max_length=30)
    scope_status: Literal["aligned", "partial", "beyond_scope", "uncertain"] = "uncertain"
    reason: str = Field(min_length=1, max_length=1800)
    evidence: list[Evidence] = Field(default_factory=list, max_length=8)
    assessment_status: Literal["matches_guidance", "different_format", "unknown"] = "unknown"
    assessment_reason: str = Field(default="No current assessment evidence has been established.", max_length=1200)
    assessment_evidence: list[Evidence] = Field(default_factory=list, max_length=4)
    reviewed: bool = False


class Analysis(StrictModel):
    matches: list[Match] = Field(max_length=50)


class GuidanceQuote(StrictModel):
    source: str = Field(max_length=8)
    page: int = Field(ge=1, le=60)
    quote: str = Field(min_length=8, max_length=1600)


class Decision(StrictModel):
    # All fields required: small local models must explicitly express uncertainty.
    reason: str = Field(
        min_length=1, max_length=1800, description="Briefly compare the question's specific concept and action with scope; check exclusions first."
    )
    objective_keys: list[str] = Field(max_length=8)
    scope_status: Literal["aligned", "partial", "beyond_scope", "uncertain"]
    assessment_reason: str = Field(min_length=1, max_length=1200)
    assessment_status: Literal["matches_guidance", "different_format", "unknown"]
    guidance: list[GuidanceQuote] = Field(max_length=4)


class GeneratedQuestionDraft(StrictModel):
    text: str = Field(min_length=10, max_length=5000)
    objective_keys: list[str] = Field(min_length=1, max_length=4)
    guidance: list[GuidanceQuote] = Field(default_factory=list, max_length=2)


class QuestionGeneration(StrictModel):
    questions: list[GeneratedQuestionDraft] = Field(min_length=1, max_length=30)
