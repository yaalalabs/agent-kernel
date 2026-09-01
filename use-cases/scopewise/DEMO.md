# ScopeWise competition demo — 4:50 target

Use an invited test account and hide credentials, invitation codes, Telegram linking codes, and personal material. The built-in database sample is original synthetic material with human-authored judgments; say that on camera. A prepared live-model result must be labeled as prepared and must come from an actual run.

## 0:00–0:35 — establish the problem

**Click:** Home → **Explore sample module**.

**Show:** the database module, the coverage summary, and the two labels on a reviewed question.

**Say:** “Searching for a topic gives me videos and papers at every depth. ScopeWise asks a narrower question: which old questions fit the exact module I study now, and which still match today's expected answer format? Those are separate judgments.”

Expected evidence: the page says “Not exam readiness,” the sample is labeled synthetic, and syllabus fit is visually separate from assessment fit.

## 0:35–1:15 — prove the evidence boundary

**Click:** Review questions → open Q1 **Review both decisions** → open its source citation. Then open Q4 and Q5.

**Show:** Q1 is syllabus-relevant but asks for a different format; Q4 cites an explicit BCNF-proof exclusion; Q5 indexing remains uncertain.

**Say:** “A missing topic is not automatically excluded. Beyond-scope needs explicit current evidence. Every positive link keeps the exact document, page, and quote.”

Expected evidence: both judgment columns, exact citations, no generated answer, and the human confirmation control.

## 1:15–1:55 — make curriculum change visible

**Click:** Home → Module settings → change the lecturer → **Update module**.

**Show:** the Change impact card, stale comparison/pack counts, “Review current sources,” and the event history. Go to Add sources and show that current assessment guidance needs reconfirmation.

**Say:** “A lecturer change does not prove the paper changed. ScopeWise records what became stale, withdraws the old guidance approval, and asks for current evidence.”

Expected evidence: the card uses that caveat exactly and never predicts a question, probability, or lecturer style.

## 1:55–3:00 — show real Agent Kernel execution

Use a prepared module made from the original files in `sample_data/`, or permission-cleared material. If the run is prepared, say how long it took and do not imply it happened during the previous minute.

**Click:** Review questions → open a result → **Review both decisions** → inspect **How this comparison was made** → expand **Technical details for judges**.

**Show:** “Compared by the local ScopeWise agent,” Meaning search or Keyword fallback, candidate/exclusion counts, guidance excerpts, the final-decision reminder, `AgentService`, and `scopewise_align`.

**Say:** “Agent Kernel is on the execution path. AgentService runs the registered alignment agent. Local retrieval narrows candidate objectives, explicit exclusions are checked first, and the server validates every returned alias and citation.”

Then click **Ask about this module** and ask: **“What changed, and what should I review next?”** Show the grounded answer from `get_change_impact`.

Fallback: if Ollama is unavailable, show the saved run details and run `python -m scripts.judge_check --full` in a terminal. State that the live model gate is unavailable; use **Start without AI** rather than staging model output.

## 3:00–3:45 — demonstrate human correction

**Click:** Review questions → open one judgment → **Correct evidence or decision**. Change or confirm the evidence and tick the human-review checkbox → **Save judgment**.

**Show:** model output began unreviewed; only the user's reviewed judgment can enter a pack; changing it invalidates packs built from the earlier review.

**Say:** “The agent proposes. The student or lecturer decides. The correction becomes a tracked course change rather than silently rewriting history.”

## 3:45–4:20 — produce useful practice

**Click:** Make a pack → **Build practice pack** → **Download / print**.

**Show:** source references, the omitted exact duplicate, independent fit labels, and the uncovered SQL-join objective.

**Say:** “The pack optimizes reviewed objective coverage, removes exact repeats, and keeps the gaps visible. Coverage describes these supplied objectives, not the student's mastery.”

## 4:20–4:40 — supported user interface

With a real bot and HTTPS webhook configured beforehand, open a private Telegram chat.

**Send:** `/courses`, `/use 1`, then **“Which objectives still need practice?”**

**Show:** a response from the same Agent Kernel assistant and tools.

Fallback: if live Telegram is not verified, show the web assistant and the deterministic Telegram test result. Say clearly that this is not a live messaging demonstration and leave its submission checkbox unchecked.

## 4:40–4:50 — close on value and evidence

**Say:** “ScopeWise makes old learning material usable in a changing module. It reduces wasted study time, keeps uncertainty visible, and supports SDG 4 without a mandatory paid model API.”

End on `COMPETITION.md` and `EVALUATION.md`. State the tested model and deployment status exactly as recorded; do not claim production capacity, public HTTPS, live Telegram, or general accuracy without the corresponding evidence.
