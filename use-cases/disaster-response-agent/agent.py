"""
Disaster Response & Resource Coordination Agent
SDG 11 - Sustainable Cities and Communities | SDG 13 - Climate Action

Three OpenAI Agents SDK agents, run on Agent Kernel, chained via handoffs so a single
incoming message (e.g. "Need drinking water in Galle") flows through the full pipeline
in one turn:

  intake_agent  --handoff-->  priority_matching_agent  --handoff-->  dedup_dispatch_agent

  1. intake_agent            parses free-form text into structured intent/resource/qty/location
  2. priority_matching_agent scores urgency (tool) and matches needs<->offers across all
                              regions, weighing quantity coverage, distance, and transport (tool)
  3. dedup_dispatch_agent    checks memory for existing pending records, creates/merges, and
                              dispatches a (dummy) WhatsApp notification to the matched party

`AGENTS` is imported by cli.py and api.py so the exact same agent definitions run both
locally on the CLI and behind the REST API.
"""

import os

from agentkernel.openai import OpenAIToolBuilder
from agents import Agent
from dotenv import load_dotenv

# Load environment variables from a .env file in the project root, if one exists, before
# anything below reads os.environ. This means GEMINI_API_KEY, WHATSAPP_ENABLED, etc. can all
# live in one .env file instead of being set with $env:/export every terminal session - see
# .env.example and the "Keeping your environment variables in one place" section in README.md.
# Real environment variables (already set with $env:/export) still take priority over .env.
load_dotenv()

from tool import (
    check_pending_duplicates,
    dispatch_notification,
    finalize_record,
    get_region_status,
    match_resources,
    score_urgency,
    submit_intake,
)

# ----------------------------------------------------------------------------------
# LLM provider: Gemini only.
#
# Every agent's LLM calls are routed to Google's Gemini API via LiteLLM's native Gemini
# integration (the openai-agents SDK's officially supported way to use non-OpenAI models).
#     $env:GEMINI_API_KEY = "..."                   # from https://aistudio.google.com/apikey
#     $env:GEMINI_MODEL = "gemini-3.1-flash-lite"    # optional, this is already the default
#
# gemini-3.1-flash-lite (GA since May 2026) is Google's low-latency, cost-efficient model
# built for high-volume agentic workflows - including tool calling and orchestration, which
# this pipeline relies on heavily for tool calls and handoffs. gemini-2.5-flash and
# gemini-2.5-pro are solid fallbacks if you need to compare quality/cost trade-offs.
#
# Note: this uses LiteLLM rather than Gemini's OpenAI-compatible endpoint on purpose. Google
# is rolling out a new API key format (prefixed "AQ." instead of the old "AIza..."), and as of
# mid-2026 those new-format keys are unreliable against the OpenAI-compat endpoint (returns
# spurious auth/model errors), while the native Gemini API - which is what LiteLLM calls -
# works fine with either key format.
# ----------------------------------------------------------------------------------
from agents import ModelSettings, set_tracing_disabled
from agents.extensions.models.litellm_model import LitellmModel
from agents.retry import ModelRetryBackoffSettings, ModelRetrySettings
from agents import retry_policies

set_tracing_disabled(True)  # tracing uploads to OpenAI's dashboard, which Gemini can't receive

_gemini_api_key = os.environ.get("GEMINI_API_KEY")
if not _gemini_api_key:
    raise RuntimeError("GEMINI_API_KEY must be set (get one at https://aistudio.google.com/apikey).")

LLM_MODEL = LitellmModel(
    model=f"gemini/{os.environ.get('GEMINI_MODEL', 'gemini-3.1-flash-lite')}",
    api_key=_gemini_api_key,
)

# Auto-retry with exponential backoff on rate limits (429, common on Gemini's free tier - each
# user message triggers 3 chained LLM calls across the agent handoffs, so a burst of messages
# can hit a low free-tier requests-per-minute quota) and transient server-side errors (5xx).
# Without this, a single 429 would surface as "Error: Too many requests" and drop that turn.
MODEL_SETTINGS = ModelSettings(
    retry=ModelRetrySettings(
        max_retries=5,
        backoff=ModelRetryBackoffSettings(initial_delay=1.0, max_delay=20.0, multiplier=2.0, jitter=True),
        policy=retry_policies.http_status([429, 500, 502, 503, 504]),
    ),
)

# ----------------------------------------------------------------------------------
# 3. Dedup & Dispatch Agent (defined first so it can be referenced in the handoff chain)
# ----------------------------------------------------------------------------------
DEDUP_DISPATCH_INSTRUCTIONS = """
You are the Dedup & Dispatch Agent, the final step in a disaster relief coordination pipeline.

You take over after the Priority & Matching Agent has already scored urgency (for needs) and
found candidate matches, which may be in the SAME region or a NEARBY region (matching now
searches across regions and reports distance_km and a transport_note for each candidate).
The intake_id and its history are visible earlier in this conversation.

Do the following, in order, calling each tool exactly once:
1. Call check_pending_duplicates(intake_id) to see if an existing OPEN request/offer already
   exists in the same region for the same resource_type.
2. Decide if any duplicate returned is genuinely the same ongoing need/offer (same resource_type,
   same region, still open). If so, call finalize_record(intake_id, duplicate_id=<that id>) to
   merge into it instead of creating a new entry. Otherwise call finalize_record(intake_id) with
   no duplicate_id to create a new record.
3. Look at the matches the Priority & Matching Agent already found. If there is a strong match
   (match_score >= 50) for the resource_type, call
   dispatch_notification(record_id=<id from finalize_record>, matched_id=<the matched offer or
   need id>) to simulate notifying the matched volunteer/donor over WhatsApp. If there is no
   good match, skip this step.
4. Reply to the user with a short, clear confirmation covering:
   - what was recorded (resource, quantity, region)
   - urgency band, if this was a "need"
   - whether it was merged with an existing pending record or created new
   - whether a match was found; if dispatch_notification was called, check its
     whatsapp_send_result field - if sent is true, say the notification was actually delivered
     via WhatsApp to the named contact; if sent is false, say it was matched but the WhatsApp
     notification could not be sent (mention the reason briefly) so the coordinator should
     follow up manually
   - if dispatch_notification's cross_region field is true, explicitly flag that the match is
     in a different region (mention the distance_km) so the coordinator knows to confirm
     transport/delivery before treating it as settled
   - if nothing matched yet, say it remains open and pending a match

Keep the final reply concise (3-5 sentences), written for a relief coordinator, not a developer.
Never expose internal ids like intake_id in your reply to the user.
"""

dedup_dispatch_agent = Agent(
    name="dedup_dispatch_agent",
    model=LLM_MODEL,
    model_settings=MODEL_SETTINGS,
    handoff_description=(
        "Checks memory for duplicate pending requests/offers in the same region, "
        "creates or merges the record, and dispatches a WhatsApp notification to a matched "
        "volunteer or donor."
    ),
    instructions=DEDUP_DISPATCH_INSTRUCTIONS,
    tools=OpenAIToolBuilder.bind([check_pending_duplicates, finalize_record, dispatch_notification]),
)

# ----------------------------------------------------------------------------------
# 2. Priority & Matching Agent
# ----------------------------------------------------------------------------------
PRIORITY_MATCHING_INSTRUCTIONS = """
You are the Priority & Matching Agent in a disaster relief coordination pipeline.

You take over right after the Intake Agent, which has just called submit_intake and produced
an intake_id visible earlier in this conversation.

Do the following, in order:
1. If the intake's message_type is "need": read the original raw_message and identify any
   vulnerable-group indicators mentioned (children, elderly, pregnant, disabled, medical/sick).
   Call score_urgency(intake_id, vulnerable_groups="<comma separated groups you identified, or
   empty string if none>"). This tool computes the actual urgency score - do not invent a score
   yourself.
   If the intake's message_type is "offer", skip urgency scoring entirely (offers are not scored).
2. Call match_resources(intake_id) to find candidate matches (offers for a need, or open needs
   for an offer). The tool now searches across ALL regions, not just this one, and scores each
   candidate on quantity coverage, proximity (same-region beats a nearby region beats a distant
   one), and transport compatibility (e.g. a requester with no transport paired with a donor
   who can deliver). You do not need to reason about distance/transport yourself - the tool's
   match_score, distance_km, and transport_note already reflect it.
3. Hand off to the Dedup & Dispatch Agent to finalize the record and notify a match. Do not
   reply to the user yourself - the Dedup & Dispatch Agent sends the final reply.
"""

priority_matching_agent = Agent(
    name="priority_matching_agent",
    model=LLM_MODEL,
    model_settings=MODEL_SETTINGS,
    handoff_description=(
        "Scores urgency for needs using vulnerable-group indicators and matches open needs "
        "against available offers (or vice versa) across all regions, weighing quantity "
        "coverage, proximity/distance, and transport compatibility."
    ),
    instructions=PRIORITY_MATCHING_INSTRUCTIONS,
    tools=OpenAIToolBuilder.bind([score_urgency, match_resources]),
    handoffs=[dedup_dispatch_agent],
)

# ----------------------------------------------------------------------------------
# 1. Intake Agent (default/entry agent)
# ----------------------------------------------------------------------------------
INTAKE_INSTRUCTIONS = """
You are the Intake Agent for a Disaster Response & Resource Coordination system used during
floods and other disasters (SDG 11 - Sustainable Cities and Communities, SDG 13 - Climate
Action). Field workers and volunteers send free-form messages like:
  - "Need drinking water in Galle"
  - "We have 50 food packs available in Colombo"
  - "Elderly couple needs medicine urgently in Matara, no transport"

CLASSIFICATION RULE (apply this first, before anything else):
  - If the message reports or implies a need or an available resource for a disaster
    situation - using words like "need", "require", "want", "we have", "available", "offering",
    "can provide", or simply stating a shortage/surplus - it is ALWAYS case (a) below, a NEW
    need/offer to record. This is true even if you already know of a matching offer/need, even
    if you could technically answer the question yourself, and even if the message reads like
    it could be a question.
  - ONLY classify a message as case (b), a status/tracking question, if the person is explicitly
    asking to look something up - e.g. "what's the status in Galle", "any pending requests in
    Matara?", "how many offers do we have for water", "list open needs".
  - When genuinely unsure, default to case (a). Recording a real need/offer is the core job of
    this system - never skip it to answer conversationally instead.

(a) NEW need or offer to record:
  1. Determine message_type: "need" (they require something) or "offer" (they have something
     available to give).
  2. Extract resource_type (e.g. "drinking water", "food packs", "medicine", "shelter",
     "blankets", "clothing"), quantity (integer; use 1 if not specified), unit (e.g. "liters",
     "packs", "people", "boxes"; use "units" if unclear), and location (the region/town).
  3. Extract contact_name / contact_phone only if explicitly given in the message; otherwise
     leave them as empty strings. Never invent contact details.
  4. If the location/region is missing entirely, ask ONE short clarifying question instead of
     calling any tool.
  5. Otherwise, call submit_intake with the extracted fields exactly once.
  6. Immediately hand off to the Priority & Matching Agent to continue processing.

(b) Status/tracking question:
  - Call get_region_status(region) directly and answer the user's question from the result.
    Do not hand off.

FORBIDDEN: never describe existing offers/needs, suggest a match, or ask the user whether they
want to "take" an offer yourself in case (a) - that is the Priority & Matching Agent's and the
Dedup & Dispatch Agent's job, further down the pipeline. Your only outputs for a new need/offer
are: one clarifying question (only if region is missing), or a submit_intake call followed by a
handoff. Do not write a final reply to the user yourself when handing off - let the pipeline
finish and the Dedup & Dispatch Agent will send the final confirmation.

Be fast and decisive: don't ask for clarification unless the region is truly missing.
"""

intake_agent = Agent(
    name="intake_agent",
    model=LLM_MODEL,
    model_settings=MODEL_SETTINGS,
    handoff_description=(
        "Parses free-form disaster relief messages into structured intent, resource type, "
        "quantity, and location, and answers region status/tracking questions."
    ),
    instructions=INTAKE_INSTRUCTIONS,
    tools=OpenAIToolBuilder.bind([submit_intake, get_region_status]),
    handoffs=[priority_matching_agent],
)

# intake_agent is listed first so it becomes the default agent selected by the CLI/REST API.
AGENTS = [intake_agent, priority_matching_agent, dedup_dispatch_agent]
