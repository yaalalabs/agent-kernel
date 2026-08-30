"""Local CLI entry point that exercises the full agent graph without WhatsApp.

Agent Kernel's built-in `CLI.main()` generates a fresh uuid4 session id per run and takes no
arguments, so it cannot pretend to be a specific WhatsApp sender. Since every tool resolves
the mother from the session id, this demo drives `AgentService` directly instead, which
accepts a session id through its public `select()` method.
"""

import argparse
import asyncio
from datetime import date, timedelta

from dotenv import load_dotenv

# See the note in server.py: .env must reach os.environ for the OpenAI SDK to find its key.
load_dotenv()

from agentkernel.core import AgentService  # noqa: E402
from agentkernel.openai import OpenAIModule  # noqa: E402

import store  # noqa: E402
from agent import AGENTS  # noqa: E402

ENTRY_AGENT = "mathru_triage"

# A demo sender, in the same shape the WhatsApp integration produces: E.164 without the '+'.
DEFAULT_SESSION_ID = "94771234567"
SAMPLE_PHM_PHONE = "94112223344"
SAMPLE_FIRST_NAME = "Nimali"
SAMPLE_MOH_AREA = "Colombo"
SAMPLE_EDD_OFFSET_DAYS = 120

OpenAIModule(AGENTS)


def seed(session_id: str) -> None:
    """Register a sample mother and sample PHM for the demo session.

    The EDD is derived from today so the seeded record stays valid however long from now the
    demo is run.
    """
    edd = date.today() + timedelta(days=SAMPLE_EDD_OFFSET_DAYS)
    record = store.upsert_mother(
        session_id=session_id,
        first_name=SAMPLE_FIRST_NAME,
        moh_area=SAMPLE_MOH_AREA,
        phm_phone=SAMPLE_PHM_PHONE,
        edd_iso=edd.isoformat(),
    )
    print(
        f"Seeded {record['first_name']} in {record['moh_area']}, EDD {record['edd_iso']}, "
        f"assigned PHM {store.redact_phone(record['phm_phone'])}."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Mathru agent graph locally.")
    parser.add_argument(
        "--session-id",
        default=DEFAULT_SESSION_ID,
        help=f"Phone number to impersonate as the sender (default: {DEFAULT_SESSION_ID}).",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Register a sample mother and PHM for this session before starting.",
    )
    return parser.parse_args()


async def run(session_id: str) -> None:
    service = AgentService()
    service.select(session_id=session_id, name=ENTRY_AGENT)

    registered = store.get_mother(session_id) is not None
    print(f"Mathru demo. Session {store.redact_phone(session_id)}, database {store.db_path()}.")
    print(f"This sender is {'registered' if registered else 'not registered'}.")
    print("Commands: !clear to reset the conversation, !quit to exit.\n")

    while True:
        try:
            prompt = (await asyncio.to_thread(input, "(you) >> ")).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return

        if not prompt:
            continue
        if prompt in ("!q", "!quit"):
            return
        if prompt in ("!c", "!clear"):
            service.clear()
            print("Conversation cleared. The registration record is untouched.\n")
            continue

        try:
            print(f"\n(mathru) {await service.run(prompt=prompt)}\n")
        except Exception as exc:  # noqa: BLE001 - a demo REPL should survive a bad turn
            print(f"\nError: {exc}\n")


def main() -> None:
    args = parse_args()
    if args.seed:
        seed(args.session_id)
    try:
        asyncio.run(run(args.session_id))
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
