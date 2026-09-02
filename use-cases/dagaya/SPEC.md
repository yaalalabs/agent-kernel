# ⚙️ Technical Agent Specification (SPEC.md)

*This document defines the exact technical contracts, constraints, and state management rules for the Dagaya multi-agent system.*

---

## 1. System-Level Architecture & Philosophy

Dagaya employs a **Hub-and-Spoke** multi-agent topology.

- **The Hub**: `dagaya_triage` acts as the intelligent router. It holds no domain knowledge but is an expert at intent classification and language detection. It **never** answers educational questions directly.
- **The Spokes**: Specialized sub-agents (`dagaya_tutor`, `dagaya_quiz`, `dagaya_track`) hold deep domain instructions and rely on the Hub for initial routing. Spokes can also cross-handoff to each other seamlessly.

### 1.1 LLM Resilience Strategy (Dynamic Fallback)

Dagaya is designed for extreme resilience and cost-efficiency in developing regions.

- **Tier 1 (Multi-Lingual & Primary)**: Google Gemini Flash / Lite. Used for the majority of interactions due to robust native support for Sinhala and Tamil.
- **Tier 2 (Speed & Fallback)**: Groq API (Llama 3 / Qwen series). Triggered automatically if the Gemini API returns HTTP 429 Rate Limit or is unavailable.

Both tiers are validated at startup in `server.py`. Working models are ranked and configured as a fallback chain via `AK_FALLBACK_MODELS`.

### 1.2 Content Guardrail

Before any message reaches the LLM, it passes through `check_guardrail(message)` in `tools.py`. This function uses compiled regex pattern matching to block:

- Violence, weapons, self-harm references
- Adult / explicit content
- Hate speech

Blocked messages receive an immediate, safe refusal reply with **zero** LLM calls.

---

## 2. Core Agent Contracts

### 2.1 Router Agent: `dagaya_triage`

- **Role**: Intent classification, language detection, and routing.
- **Input**: Unstructured natural language from the WhatsApp Webhook.
- **System Constraints**:
  1. **Language Detection**: Must detect the language of the incoming message (English, Sinhala, Tamil, Hindi) and call `set_preferred_language` to persist it.
  2. **Context Extraction**: If the user provides their name, country, or target exam, the agent must silently call `set_student_context` before routing.
  3. **No Answering**: Must *never* attempt to answer educational questions directly.
- **Available Tools**: `set_preferred_language`, `set_student_context`, `get_student_profile`
- **Handoffs**: `dagaya_tutor`, `dagaya_quiz`, `dagaya_track`

### 2.2 Domain Agent: `dagaya_tutor`

- **Role**: Contextualized, pedagogical explanation using the Socratic method.
- **System Constraints**:
  1. **Socratic Method**: Never provide a direct answer. Ask guiding questions that force the student to think.
  2. **Global Grounding**: Uses the student's country and target exam (from `get_student_profile`) to localize all examples.
  3. **Visual Learning**: Must call `search_images_online` whenever a visual would aid understanding.
- **Available Tools**: `get_student_profile`, `get_curious_fact`, `search_online`, `search_images_online`
- **Handoffs**: `dagaya_quiz`, `dagaya_track`

### 2.3 Domain Agent: `dagaya_quiz`

- **Role**: Interactive knowledge testing and scoring.
- **System Constraints**:
  1. **One Question at a Time**: Generate exactly *one* multiple choice question and wait for the answer before proceeding.
  2. **Explain on Request**: If the student's answer includes "explain", provide a full explanation. Otherwise just confirm right/wrong.
  3. **Save Scores**: Must call `update_student_progress` after the quiz ends.
- **Available Tools**: `generate_quiz_topic`, `update_student_progress`, `get_student_profile`, `search_online`, `search_images_online`
- **Handoffs**: `dagaya_tutor`, `dagaya_track`

### 2.4 Domain Agent: `dagaya_track`

- **Role**: Analytics and motivation.
- **System Constraints**:
  1. **Encouragement Only**: Always frame progress positively. Never teach, explain, or give quizzes.
  2. **Route on Demand**: If the student asks a question, immediately hand off to `dagaya_tutor`.
- **Available Tools**: `get_student_profile`
- **Handoffs**: `dagaya_tutor`, `dagaya_quiz`

---

## 3. State Management & Memory Injection

Dagaya utilizes Agent Kernel's native `Session` object to achieve statefulness over WhatsApp (which is naturally stateless).

- **ToolContext Interface**: Every tool in `tools.py` reads/writes state via `ToolContext.get().session.get_non_volatile_cache()`.
- **Memory Schema**:
  ```json
  {
    "student_profile": {
      "name": "Charaka",
      "country": "Sri Lanka",
      "exam": "GCE O/L",
      "preferred_language": "en",
      "quiz_history": {
        "science": [{"score": 3, "max_score": 5}]
      },
      "weak_topics": ["science"]
    }
  }
  ```
- **Persistence**: Configured to `in_memory` for local demos. Production deployments swap `config-whatsapp.yaml` to use the `redis` backend for persistent multi-user WhatsApp state.

---

## 4. Live Demo

A beta deployment of Dagaya is live and accessible at:
**🌐 https://ulfheonar.com/dagaya**

The WhatsApp bot is actively running and open for testing.
