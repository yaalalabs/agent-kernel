"""Tool functions for the Volunteer Matching Platform.

- search_opportunities: deterministic scoring over data/opportunities.json. No agent/LLM
  call involved, so it's directly unit-testable (see tool_test.py).
- save_user_profile / load_user_profile: persist/read the current user's profile via a
  ChromaManager knowledge base, keyed by a stable user_id resolved internally (see
  _current_user_id) rather than passed in by the LLM — see the note on that function for why.

Bound to agents in agent.py via PydanticAIToolBuilder.bind([...]).
"""

from __future__ import annotations

import json
from pathlib import Path

from agentkernel.core import ToolContext
from agentkernel.core.model import AgentRequestAny
from agentkernel.knowledgebase.chroma import ChromaManager

_OPPORTUNITIES_PATH = Path(__file__).parent / "data" / "opportunities.json"

_PROFILE_STORE_PATH = str(Path(__file__).parent / "chroma_db")
_PROFILE_COLLECTION = "volunteer_user_profiles"

_profile_store: ChromaManager | None = None


def _get_profile_store() -> ChromaManager:
    """Lazily construct the profile knowledge store on first use, not at import time."""
    global _profile_store
    if _profile_store is None:
        _profile_store = ChromaManager(
            persist_path=_PROFILE_STORE_PATH,
            name="user_profiles",
            collection_name=_PROFILE_COLLECTION,
            description="Stores each user's captured volunteer profile so it can be recalled in later sessions.",
        )
    return _profile_store


def _current_user_id() -> str:
    """Resolve a stable identity for the current user across separate conversations.

    The installed agentkernel version (0.8.1) does not propagate a chat request's user_id
    down to tools (verified directly: RequestBuilder._attach_additional_context explicitly
    excludes "user_id" as a "known field", and neither ToolContext nor Session exposes an
    acting-user accessor in this version) — an earlier draft of this function assumed a
    newer, unreleased acting-user-propagation feature only present in the monorepo's
    `develop` source, not in what this project actually depends on. Real behavior instead:

    - Slack: AgentSlackRequestHandler attaches the raw Slack event as
      AgentRequestAny(name="body", content=body); body["user"] is the Slack user id, which
      stays the same across separate conversations/threads (unlike session_id, which is the
      thread timestamp and changes per conversation) — so it's read directly from there.
    - Everything else (web frontend, CLI): falls back to the current Agent Kernel
      session.id. This only gives cross-*visit* memory if the caller reuses the same
      session_id across visits — the web frontend does this deliberately (persisted in
      localStorage, see static/index.html) instead of generating a fresh one per page load.
      The CLI gets a fresh session_id per run, so CLI memory only persists within one run.
    """
    ctx = ToolContext.get()
    for req in ctx.requests:
        if isinstance(req, AgentRequestAny) and req.name == "body":
            body = req.content
            if isinstance(body, dict) and body.get("user"):
                return f"slack:{body['user']}"
    return ctx.session.id


def search_opportunities(
    skills: list[str],
    causes: list[str] | None = None,
    location: str | None = None,
    remote_ok: bool = True,
) -> list[dict]:
    """Rank volunteer opportunities from data/opportunities.json against the given profile.

    Scoring is deterministic: each matching skill is worth more than each matching cause,
    and a location/remote match adds a smaller bonus on top — so a strong skill match always
    outranks a weak one padded only by cause/location overlap. When any skills or causes are
    given, only opportunities overlapping at least one of them are returned (location/remote
    fit alone is not enough); with neither given, location/remote fit decides. An empty result
    means no good match exists, which the calling agent should say plainly rather than
    presenting a weak match as if it were a good one.

    :param skills: The user's skills, matched case-insensitively against each opportunity's
        required_skills.
    :param causes: The user's causes of interest, matched case-insensitively against each
        opportunity's cause_tags.
    :param location: The user's city/region, matched as a case-insensitive substring against
        an opportunity's location.
    :param remote_ok: Whether the user is open to remote opportunities.
    :return: Up to 5 matching opportunities, highest score first, each with the original
        fields plus `score` and a human-readable `justification` string.
    """
    with open(_OPPORTUNITIES_PATH, encoding="utf-8") as f:
        opportunities = json.load(f)

    normalized_skills = {s.strip().lower() for s in skills if s and s.strip()}
    normalized_causes = {c.strip().lower() for c in (causes or []) if c and c.strip()}
    normalized_location = (location or "").strip().lower()

    scored = []
    for opp in opportunities:
        opp_skills = {s.lower() for s in opp.get("required_skills", [])}
        opp_causes = {c.lower() for c in opp.get("cause_tags", [])}

        matched_skills = normalized_skills & opp_skills
        matched_causes = normalized_causes & opp_causes

        score = len(matched_skills) * 10 + len(matched_causes) * 5

        location_matched = False
        if opp.get("remote") and remote_ok:
            score += 3
            location_matched = True
        elif normalized_location and normalized_location in opp.get("location", "").lower():
            score += 3
            location_matched = True

        # Location/remote fit is only a tie-breaking bonus: when the user named any skills or
        # causes, an opportunity must overlap at least one of them to count as a match.
        # Otherwise every remote listing would "match" any profile on remote_ok alone, and the
        # "no strong matches" path would never be reached.
        if (normalized_skills or normalized_causes) and not (matched_skills or matched_causes):
            continue
        if score <= 0:
            continue

        reasons = []
        if matched_skills:
            reasons.append(f"matches your skills in {', '.join(sorted(matched_skills))}")
        if matched_causes:
            reasons.append(f"aligns with your interest in {', '.join(sorted(matched_causes))}")
        if location_matched:
            reasons.append("fits your location/remote preference")
        justification = ("This opportunity " + "; ".join(reasons) + ".") if reasons else ""

        scored.append({**opp, "score": score, "justification": justification})

    scored.sort(key=lambda o: o["score"], reverse=True)
    return scored[:5]


def save_user_profile(skills: list[str], availability: str, causes: list[str], location: str) -> str:
    """Persist the current user's profile to the knowledge store, keyed by their stable user id.

    :param skills: The user's skills.
    :param availability: The user's stated availability (free-text, e.g. "weekends, 3 hrs").
    :param causes: Causes/topics the user cares about.
    :param location: The user's city/region, or "Remote" if they prefer remote opportunities.
    :return: A short confirmation string.
    """
    store = _get_profile_store()
    summary = (
        f"Skills: {', '.join(skills)}. Availability: {availability}. Causes: {', '.join(causes)}. Location: {location}."
    )
    store.collection.upsert(
        ids=[_current_user_id()],
        documents=[summary],
        metadatas=[
            {
                "skills": json.dumps(skills),
                "availability": availability,
                "causes": json.dumps(causes),
                "location": location,
            }
        ],
    )
    return "Profile saved."


def load_user_profile() -> dict | None:
    """Load the current user's previously saved profile.

    :return: A dict with skills/availability/causes/location, or None if this user has no
        saved profile yet (a new user).
    """
    store = _get_profile_store()
    result = store.collection.get(ids=[_current_user_id()])
    ids = result.get("ids") or []
    if not ids:
        return None

    meta = (result.get("metadatas") or [{}])[0]
    return {
        "skills": json.loads(meta.get("skills", "[]")),
        "availability": meta.get("availability", ""),
        "causes": json.loads(meta.get("causes", "[]")),
        "location": meta.get("location", ""),
    }
