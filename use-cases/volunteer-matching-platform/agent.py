import logging

from agentkernel.pydanticai import PydanticAIToolBuilder
from pydantic_ai import Agent

from tool import load_user_profile, save_user_profile, search_opportunities

_log = logging.getLogger("ak.vmp.handoff")

# Google Gemini via the free Google AI Studio tier (GEMINI_API_KEY / GOOGLE_API_KEY env var) —
# no OpenAI key or card required. gemini-2.5-flash was retired for new API keys (Google's own
# API error points here instead); gemini-3.6-flash (launched July 2026) is the current
# free-tier flash model — verify this is still current if picking it back up much later, models
# retire on a schedule. Swap the prefix for "openai:...", "anthropic:...", etc. if the team
# later wants a different provider (also swap the pydantic-ai-slim[google] extra to match).
MODEL = "google:gemini-3.6-flash"

MATCHING_AGENT_INSTRUCTIONS = """
You are the matching agent for a Volunteer Matching Platform (SDG 17 — Partnerships for the Goals).

You receive a short summary of a user's captured profile, in the form:
"Skills: a, b. Availability: ... . Causes: c, d. Location: ... ."

1. Extract from that summary: the list of skills, the list of causes, the location (or note if
   it says "Remote"), and whether the user is open to remote work (treat "Remote" as remote_ok=true;
   otherwise assume remote_ok=true unless the summary clearly says they want in-person only).
2. Call search_opportunities with those extracted values.
3. If it returns one or more opportunities, present the top matches (up to 5) as a short list.
   For each: the organization, the title, the time commitment, and its `justification` field
   rephrased naturally in one sentence. Do not invent matches or details not present in the
   tool's result.
4. If it returns an empty list, say plainly that no strong matches were found right now, and
   suggest the user broaden their causes, skills, or location/remote preference. Do not force a
   weak match just to have something to show.

Keep the whole reply concise — a short intro line plus the list, nothing more.
"""

matching_agent = Agent(
    model=MODEL,
    name="matching_agent",
    description="Ranks volunteer opportunities against a captured profile and justifies the matches.",
    instructions=MATCHING_AGENT_INSTRUCTIONS,
    tools=PydanticAIToolBuilder.bind([search_opportunities]),
)


# Pydantic AI has no handoffs= primitive (unlike the OpenAI Agents SDK) — multi-agent routing is
# delegation-via-tool: profile_agent calls this tool once it has enough information, which runs
# matching_agent and returns its output as the reply.
async def hand_off_to_matching_agent(profile_summary: str) -> str:
    """Delegate to the matching agent once the user's profile has been captured and saved.

    :param profile_summary: A one-line summary in the exact form "Skills: a, b. Availability:
        .... Causes: c, d. Location: ... ." — the same shape save_user_profile stores, so
        matching_agent can parse it reliably.
    """
    # This nested call runs matching_agent directly via Pydantic AI, not through Agent
    # Kernel's AgentService — so it never shows up as "Selected agent: matching_agent" in
    # the terminal the way profile_agent's own selection does. This log line is the only
    # visible confirmation that the handoff actually happened.
    _log.info("Delegating to matching_agent with profile_summary=%r", profile_summary)
    reply = str((await matching_agent.run(profile_summary)).output)
    _log.info("matching_agent replied (%d chars)", len(reply))
    return reply


PROFILE_AGENT_INSTRUCTIONS = """
You are the profile agent for a Volunteer Matching Platform (SDG 17 — Partnerships for the Goals).
Your job is to learn a user's skills, availability, causes of interest, and location, then hand
off to the matching agent — nothing more.

1. At the very start of every conversation, call load_user_profile() exactly once, before saying
   anything else to the user.
2. If it returns a saved profile: greet the user, briefly restate what you already know about
   them (skills, availability, causes, location), and ask only whether anything has changed —
   do not re-ask questions you already have answers to.
3. If it returns None: this is a new user. Conversationally collect all four of:
   - skills (a list, e.g. "teaching, first aid")
   - availability (free text, e.g. "weekends, about 3 hours")
   - causes they care about (a list, e.g. "education, environment")
   - location, or "Remote" if they'd rather volunteer remotely
   Ask naturally, not as a rigid form — but do not proceed until you have all four.
4. Once you have a complete profile (new or updated), call save_user_profile with it.
5. Then call hand_off_to_matching_agent with a one-line summary in exactly this form:
   "Skills: a, b. Availability: .... Causes: c, d. Location: ... ."
6. Return whatever hand_off_to_matching_agent gives back as your reply — do not add your own
   commentary on top of it.

Keep every message concise and conversational.
"""

profile_agent = Agent(
    model=MODEL,
    name="profile_agent",
    description="Captures a user's skills, availability, causes, and location, then hands off to matching.",
    instructions=PROFILE_AGENT_INSTRUCTIONS,
    tools=PydanticAIToolBuilder.bind([load_user_profile, save_user_profile, hand_off_to_matching_agent]),
)

AGENTS = [profile_agent, matching_agent]
