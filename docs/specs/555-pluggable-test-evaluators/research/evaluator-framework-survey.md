# Evaluator Framework Survey — DeepEval, Opik, Braintrust, RAGAS

Supporting research for `../design.md`. Surveys the LLM-evaluation libraries AK could sit behind
`AKEvaluator`, to establish (a) what a backend-neutral input payload must carry and (b) what a
backend-neutral result must carry.

**Status:** external claims verified against vendor documentation on 2026-08-18; §10's catalogue
matrix verified on 2026-08-19. Source links at the end of each section. Nothing here was taken from
memory. Code claims about AK carry `path:line`.

## 1. Why the survey was needed

The pre-refactor harness talks to RAGAS through two hard-coded metrics — `answer_similarity` when
expected answers exist, `answer_relevancy` otherwise (`ak-py/src/agentkernel/test/test.py:152-219`).
Both take only `(question, answer, ground_truth)`. If `AKEvaluator` were designed from that call
alone, its interface would be a three-string signature, and every metric that needs anything else
would be unreachable without changing the ABC.

## 2. The common input shape

All four libraries converged on the same four fields under different names:

| Concept | DeepEval (`LLMTestCase`) | RAGAS 0.4 (`SingleTurnSample`) | Opik (`BaseMetric.score`) | Braintrust autoevals |
|---|---|---|---|---|
| question | `input` (mandatory) | `user_input` | `input` | `input` |
| answer under test | `actual_output` (mandatory) | `response` | `output` | `output` |
| ground truth | `expected_output` | `reference` | `expected_output` | `expected` |
| retrieved context | `retrieval_context`, `context` | `retrieved_contexts` | `context: list[str]` | `context` |

DeepEval's `LLMTestCase` additionally carries `tools_called`, `expected_tools`, `token_cost`,
`completion_time`, `name`, `tags`, `flaky`. Only `input` and `actual_output` are always mandatory;
every other field is required only by the metrics that read it.

**Finding 1 — a flat `(question, answer, expected)` signature is a dead end.** Context is the
single largest unlock: Faithfulness, Hallucination, Contextual Precision/Recall/Relevancy and
Context Entity Recall all key off it, across every library.

**Finding 2 — no library accepts a list of alternative acceptable answers.** Every one takes a
single `expected_output` / `reference` / `expected`. AK's "pass if the response matches ANY of the
expected strings" (`test.py:141-149`, `test.py:190-199`) is an AK-level concept. Passing the list
down would force every backend to reimplement the same loop; the loop belongs in `Test.compare`.
Batching in these libraries happens across *test cases* (`deepeval.evaluate(test_cases, metrics)`,
RAGAS `EvaluationDataset`), never across alternatives for one answer.

**Finding 3 — some inputs are typed objects, not strings.** DeepEval's `tools_called` /
`expected_tools` are `list[ToolCall]`, where `ToolCall` has `name` (mandatory) plus optional
`description`, `reasoning`, `output` (any type), and `input_parameters` (`dict[str, Any]`).
Conversational metrics need `ConversationalTestCase(turns=[Turn(role, content, tools_called)])`;
multimodal metrics need `MLLMTestCase` with `MLLMImage`. `JsonCorrectnessMetric` takes a pydantic
`BaseModel` **class** as `expected_schema` on the metric constructor, not on the test case.

**Finding 4 — some metrics take no test case at all.** `TaskCompletionMetric` derives both task and
outcome from an `@observe` trace ("It scores the outcome of the whole run, deriving both task and
outcome from the full trace"); the same is true of `StepEfficiency`, `PlanAdherence`, and Opik's
`Trajectory Accuracy`. No `evaluate(case)` signature can reach these — they require the system under
test to run under the evaluator's instrumentation.

Sources: [DeepEval single-turn test case](https://deepeval.com/docs/evaluation-test-cases) ·
[DeepEval tool correctness](https://deepeval.com/docs/metrics-tool-correctness) ·
[DeepEval task completion](https://deepeval.com/docs/metrics-task-completion) ·
[DeepEval json correctness](https://deepeval.com/docs/metrics-json-correctness) ·
[RAGAS eval sample](https://docs.ragas.io/en/stable/concepts/components/eval_sample/) ·
[Opik ContextRecall](https://www.comet.com/docs/opik/python-sdk-reference/evaluation/metrics/ContextRecall.html) ·
[autoevals](https://github.com/braintrustdata/autoevals/blob/main/README.md)

## 3. Custom-rubric metrics are not optional extras

Each library's most-used metric is a per-test rubric evaluated by an LLM:

| Library | Class | Rubric is supplied as |
|---|---|---|
| DeepEval | `GEval` | `criteria` (or `evaluation_steps`) — constructor, required |
| Opik | `GEval` | `task_introduction` + `evaluation_criteria` — constructor, both positional-required |
| Braintrust | `LLMClassifier` | prompt template with `{{input}}` / `{{output}}` / `{{expected}}` |
| RAGAS | `AspectCritic` | `definition` |

**Finding 5 — this is load-bearing for the DeepEval migration specifically.** DeepEval ships **no
built-in embedding or semantic-similarity metric**; an `AnswerCorrectness` metric is an open feature
request ([confident-ai/deepeval#653](https://github.com/confident-ai/deepeval/issues/653)). So the
`answer_similarity` path being replaced (`test.py:188-199`) has no drop-in DeepEval equivalent — the
replacement is `GEval` with a rubric such as *"determine whether the actual output conveys the same
information as the expected output"*. A payload with nowhere to put a rubric string cannot express
AK's existing similarity check on DeepEval.

Sources: [DeepEval metrics intro](https://deepeval.com/docs/metrics-introduction) ·
[Opik GEval](https://www.comet.com/docs/opik/python-sdk-reference/evaluation/metrics/GEval.html) ·
[Opik G-Eval concept](https://www.comet.com/docs/opik/evaluation/metrics/g_eval)

## 4. Thresholds belong to the caller, and every library allows that

- **DeepEval**: `threshold` is a metric-constructor argument (default `0.5`); `threshold=None`
  enables a documented **score-only mode**. `strict_mode` forces binary 0/1 scoring.
  `include_reason` (default `True`) controls whether a rationale is generated.
- **Opik**: `score()` returns a raw `ScoreResult`; no threshold concept in the metric.
- **Braintrust**: scorers return a `Score` with a 0–1 value; thresholding is the caller's.
- **RAGAS**: `ascore()` returns a value read via `result.value`.

**Finding 6 — AK can keep `match_threshold` and the score→llm fallback chain entirely in
`Test.compare`** (`test.py:221-262`) and treat every backend as a pure scorer. Adapters construct
DeepEval metrics with `threshold=None`.

## 5. Outputs: one envelope, several failure states

DeepEval's metric contract exposes `score` (0–1), `reason`, `is_successful()`, `error`,
`verbose_logs`, and `evaluation_cost`. Opik returns `ScoreResult(name, value, reason, metadata,
scoring_failed)`. Braintrust returns `Score(name, score, metadata)`. RAGAS returns a result object
read via `.value`.

**Finding 7 — a backend can fail *without raising*.**

- Opik sets `ScoreResult.scoring_failed = True`.
- autoevals returns `score: None` for a skipped scorer.
- DeepEval sets `metric.error` and continues in batch runs.

If an adapter maps any of these to `0.0`, AK's `FALLBACK` mode (`test.py:254-262`) reports a dead API
key or a rate limit as a content mismatch, and the failure message names the expected/actual strings —
pointing the reader at the agent instead of at the judge. The AK result type therefore needs
"no score" to be representable distinctly from "score 0.0".

**Finding 8 — scores are not commensurable across metrics.** `ArgumentCorrectness` is *correctly
generated input parameters ÷ total tool calls*; `AnswerRelevancy` is a statement-level ratio;
`TaskCompletion` is `AlignmentScore(task, outcome)`. All are 0–1 and all threshold the same way, but
averaging across metrics is meaningless.

**Finding 9 — one call can produce several scores.** Opik custom metrics may return a
`list[ScoreResult]`.

Sources: [Opik custom metric](https://www.comet.com/docs/opik/evaluation/metrics/custom_metric) ·
[Opik AnswerRelevance](https://www.comet.com/docs/opik/python-sdk-reference/evaluation/metrics/AnswerRelevance.html) ·
[DeepEval answer relevancy](https://deepeval.com/docs/metrics-answer-relevancy) ·
[Braintrust autoevals docs](https://www.braintrust.dev/docs/evaluate/autoevals)

## 6. Metric-availability traps for the two built-ins

- **Opik `AnswerRelevance` requires context by default** (`require_context: bool = True`) and raises
  without it. AK's referenceless relevancy path must construct it with `require_context=False`.
- **Opik `GEval.score()` takes only `output`** (`score(output: str, **ignored_kwargs)`), with the
  documented usage being to serialize the whole scenario — question, context, answer — into that one
  string. The Opik adapter is therefore not a pure field rename; it assembles a prompt.
- **DeepEval has no semantic-similarity metric** (Finding 5).
- **Opik has no "faithfulness" metric**; its nearest equivalent is `Hallucination`, whose polarity is
  inverted. Any AK-level `faithfulness` name would need a documented inversion, which is why the v1
  metric vocabulary in `design.md` stops at similarity/relevancy/custom.

## 7. Async and sync surfaces

Every library offers both: DeepEval `measure()` / `a_measure()`, Opik `score()` / `ascore()`, RAGAS
`ascore()`, autoevals `eval()` / `eval_async()`. So AK is free to choose, and the choice is decided
by AK's own callers rather than by the backends — see `design.md` "Synchronous evaluation" for why
AK's is sync: `Test.compare` is a sync static method called from inside running event loops in
shipped examples (e.g. `examples/transport/nats/app_test.py:100-112`,
`examples/aws-serverless/openai/lambda_test.py:52-56`), where neither `asyncio.run` nor
`loop.run_until_complete` is usable.

## 8. Net requirements this survey produces

1. Payload carries `user_input`, `actual`, `expected` (single), `context`, `criteria` — the last two
   `None`-defaulted (Findings 1, 5).
2. Alternative-expected iteration stays in `Test.compare` (Finding 2).
3. Result carries `score: float | None` plus an explicit failure flag, and adapters convert soft
   backend failures into raised AK errors (Finding 7).
4. Thresholding, mode selection, and the fallback chain stay in `Test.compare`; adapters construct
   backends in score-only mode (Finding 6).
5. Metric identity travels with every result; scores are never aggregated across metrics (Finding 8).
6. Typed inputs (tool calls, turns, images) and trace-derived metrics are out of scope for this
   change and are recorded as non-goals, not designed around (Findings 3, 4).

## 9. `deepeval.scorer.Scorer` inventory and what is actually DeepEval-only

Enumerated from `deepeval/scorer/scorer.py` on `main` (2026-08-18), cross-referenced against Opik's
published heuristic-metric list, RAGAS "Traditional NLP Metrics", and Braintrust autoevals.

| `Scorer` method | Depends on | Also in Opik / RAGAS / autoevals? |
|---|---|---|
| `rouge_score` | `rouge-score` | Yes — Opik ROUGE, RAGAS traditional |
| `sentence_bleu_score` | NLTK | Yes — Opik Sentence BLEU / Corpus BLEU |
| `bert_score` | `bert-score` + PyTorch | Yes — Opik BERTScore |
| `exact_match_score` | none | Yes — Opik `Equals`, autoevals `ExactMatch` |
| `quasi_exact_match_score` | none (internal `normalize_text`) | **No** — SQuAD-style normalised match |
| `quasi_contains_score` | none (internal `normalize_text`) | **No** — Opik `Contains` is plain substring |
| `answer_relevancy_score` | sentence-transformers (self/cross-encoder) | **No** — others judge relevancy with an LLM |
| `faithfulness_score` | SummaC (SummaCZS NLI) | **No** — others judge faithfulness with an LLM |
| `hallucination_score` | Vectara HallucinationModel (HHEM) | **No** — others judge hallucination with an LLM |
| `neural_toxic_score` | Detoxify | **No** — Opik Moderation is LLM-judged |
| `neural_bias_score` | internal UnBiasedModel | **No** — Opik Bias is LLM-judged |
| `truth_identification_score` | none | **No** — niche (comma-separated integer lists) |
| `pass_at_k` | NumPy | **No** — code-generation metric |
| `squad_score` | `DeepEvalBaseLLM` | LLM-backed, not a deterministic scorer |
| `PII_score` | — | Raises `NotImplementedError`; unusable |

**Finding 10 — the DeepEval-only deterministic scorers are the *model-backed* ones plus the two
normalised matchers.** Everything DeepEval shares with the other frameworks is the classic NLP set
(ROUGE/BLEU/BERTScore/exact match). What no other surveyed framework ships is a set of small local
models used *instead of* an LLM judge — SummaC for faithfulness, Vectara HHEM for hallucination,
Detoxify for toxicity, a sentence-transformers cross-encoder for relevancy — plus SQuAD-style
`quasi_exact_match` / `quasi_contains`.

**Finding 11 — the two cost profiles are very different.** `quasi_exact_match_score` and
`quasi_contains_score` need no extra dependency and no model download, but return an **int 0 or 1**,
so they are binary and strict. The model-backed scorers return graded floats close in spirit to the
rapidfuzz ratio they would replace, but pull PyTorch and a first-run model download into any
environment that installs AK's `test` extra.

**Finding 12 — a binary score-mode default changes `fallback` economics.** `fallback` calls the LLM
only when score mode fails. With a graded scorer, near-miss answers pass locally; with a strict
binary matcher, almost every agent response fails the score stage and falls through, so effectively
every test makes an LLM call.

Sources: [`deepeval/scorer/scorer.py`](https://github.com/confident-ai/deepeval/blob/main/deepeval/scorer/scorer.py) ·
[DeepEval custom metrics guide](https://deepeval.com/guides/guides-building-custom-metrics) ·
[Opik heuristic metrics](https://www.comet.com/docs/opik/evaluation/metrics/heuristic_metrics) ·
[RAGAS traditional metrics](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/traditional/)

## 10. Cross-framework metric matrix

Enumerated from each vendor's own metric index on 2026-08-19 (links at the end of this section).
Rows are evaluation *concerns*; cells name the concrete class the framework ships for that concern, or
`—` when it ships none. Sections 2–9 compare the frameworks' *plumbing*; this compares their
*catalogues*, which is what determines whether a given `AKEvaluator` backend can answer a given
question at all.

### LLM-judged metrics

| Concern | DeepEval | Opik | RAGAS | autoevals |
|---|---|---|---|---|
| Custom rubric | `GEval`, `ConversationalGEval`, `DAGMetric` | `G-Eval`, `LLM Juries Judge` | `AspectCritic`, `SimpleCriteriaScore`, `RubricsScore` | `LLMClassifier`, `ClosedQA` |
| **Answer vs ground truth** | **—** | `Meaning Match` | `FactualCorrectness`, `AnswerAccuracy` | `AnswerCorrectness` |
| **Semantic similarity** | **—** | **—** | `SemanticSimilarity` | `AnswerSimilarity` |
| Answer relevancy (referenceless) | `AnswerRelevancyMetric` | `Answer Relevance`, `QA Relevance Judge` | `ResponseRelevancy` | `AnswerRelevancy` |
| Faithfulness / groundedness | `FaithfulnessMetric` | — (see `Hallucination`) | `Faithfulness`, `ResponseGroundedness` | `Faithfulness` |
| Hallucination | `HallucinationMetric` | `Hallucination` | — | — |
| Context precision | `ContextualPrecisionMetric` | `Context Precision` | `ContextPrecision` | `ContextPrecision` |
| Context recall | `ContextualRecallMetric` | `Context Recall` | `ContextRecall` | `ContextRecall` |
| Context relevancy | `ContextualRelevancyMetric` | — | `ContextRelevance` | `ContextRelevancy` |
| Context entity recall | — | — | `ContextEntitiesRecall` | `ContextEntityRecall` |
| Summarization | `SummarizationMetric` | `Summarization Coherence/Consistency Judge` | `Summarization` | `Summarization` |
| Toxicity / moderation | `ToxicityMetric`, `MisuseMetric` | `Moderation` | — | `Moderation` |
| Bias | `BiasMetric` | — | — | — |
| PII / policy leakage | `PIILeakageMetric`, `NonAdviceMetric`, `RoleViolationMetric` | `Compliance Risk Judge` | — | `Security` |
| Schema / structured output | `JsonCorrectnessMetric` | `Structured Output Compliance` | — | `JSONValidity` |
| Tool correctness | `ToolCorrectnessMetric`, `ArgumentCorrectnessMetric` | `Agent Tool Correctness Judge` | `ToolCallAccuracy`, `ToolCallF1` | — |
| Task / goal completion | `TaskCompletionMetric` | `Agent Task Completion Judge` | `AgentGoalAccuracy` | — |
| Trajectory / plan quality | `StepEfficiencyMetric`, `PlanAdherenceMetric`, `PlanQualityMetric` | `Trajectory Accuracy` | `TopicAdherence` | — |
| Conversational | `ConversationCompletenessMetric`, `ConversationRelevancyMetric`, `RoleAdherenceMetric`, `KnowledgeRetentionMetric` | `Conversational Coherence`, `Session Completeness Quality`, `User Frustration` | — | — |
| Multimodal | 5 image metrics (`ImageCoherenceMetric`, …) | — | `MultimodalFaithfulness`, `MultimodalRelevance` | — |
| SQL | — | — | `SQLQueryEquivalence` | `SQL` |

### Non-LLM metrics

| Concern | DeepEval | Opik | RAGAS | autoevals |
|---|---|---|---|---|
| Exact / normalised match | `Scorer.exact_match_score`, `quasi_exact_match_score`, `quasi_contains_score` | `Equals`, `Contains`, `RegexMatch` | `ExactMatch`, `StringPresence` | `ExactMatch` |
| Edit distance | — | `Levenshtein` | `NonLLMStringSimilarity` | `LevenshteinDistance` |
| N-gram overlap | `Scorer.rouge_score`, `sentence_bleu_score` | `ROUGE`, `SentenceBLEU`, `CorpusBLEU`, `ChrF`, `GLEU` | `RougeScore`, `BleuScore`, `ChrfScore` | — |
| Embedding similarity | `Scorer.bert_score` | `BERTScore` | — | `EmbeddingSimilarity` |
| **Local-model scorers** | `faithfulness_score` (SummaC), `hallucination_score` (Vectara HHEM), `answer_relevancy_score` (cross-encoder), `neural_toxic_score` (Detoxify), `neural_bias_score` | — | — | — |
| JSON structure | — | `IsJson` | — | `JSONDiff` |
| Numeric / distribution | `Scorer.pass_at_k` | `KLDivergence`, `JSDivergence`, `JSDistance`, `Spearman Ranking` | — | `NumericDifference` |
| Readability / style | — | `Readability`, `Sentiment`, `Tone`, `Language Adherence` | — | — |

**Finding 13 — the gap AK hits is DeepEval-specific and it is the ground-truth column.** Three of the
four frameworks ship a metric that scores an answer against a reference (`SemanticSimilarity`,
`AnswerSimilarity`/`AnswerCorrectness`, `FactualCorrectness`/`AnswerAccuracy`, `Meaning Match`);
DeepEval ships none, in either the LLM-judged or the embedding column. Since a reference comparison is
exactly what AK's harness does — `expect()` takes ground-truth strings — the single metric AK most
needs is the single metric its chosen backend lacks. This is the root cause of Finding 5 and the
reason the `llm` mode is a `GEval` rubric rather than a named similarity metric.

**Finding 14 — the portable core is five concerns wide.** Only *custom rubric*, *answer relevancy*,
*context precision*, and *context recall* exist in all four catalogues (*faithfulness* in three, with
Opik reachable only through inverted `Hallucination`). Everything else is at least one framework short.
A metric-name vocabulary in `AKTestConfig` would therefore either be restricted to those five or be
unimplementable by some future backend — which is the concrete argument for the design's
"one metric per mode, no metric-selection config key" decision: `score` and `llm` name *how* a backend
scores, not *what* it measures, so any catalogue can satisfy the interface.

**Finding 15 — catalogue depth is not evenly distributed.** DeepEval leads on agentic and safety
metrics (11 classes across trajectory, tool, and policy concerns) and is alone in shipping non-LLM
local-model scorers; RAGAS leads on reference comparison and retrieval; Opik leads on deterministic
text statistics and conversation-level judging; autoevals is the narrowest, being largely a RAGAS
port plus heuristics. A second built-in adapter would therefore add *coverage*, not just choice — the
non-goal list in `design.md` stays accurate, but the dotted-path escape hatch is what a user with a
RAGAS-shaped need actually reaches for.

Sources: [DeepEval metrics introduction](https://deepeval.com/docs/metrics-introduction) ·
[Opik metrics overview](https://www.comet.com/docs/opik/evaluation/metrics/overview) ·
[RAGAS available metrics](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/) ·
[autoevals README](https://github.com/braintrustdata/autoevals/blob/main/README.md)
