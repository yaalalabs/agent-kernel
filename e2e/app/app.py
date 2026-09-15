import base64
import logging
import os

from agentkernel.integration.adapter import PollerRunner, WebhookRESTRequestHandler
from agentkernel.openai import OpenAIModule
from agentkernel.pipeline import IOHandler
from agentkernel.slack import SlackInboundAdapter
from agentkernel.telegram import TelegramInboundAdapter
from agents import Agent as OpenAIAgent

general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You are an integration test agent. Reply to every message with a short, one-sentence answer.",
    model="openai/gpt-4.1-mini",
)

OpenAIModule([general_agent])

_log = logging.getLogger("ak.e2e")


def _maybe_gmail():
    """Build the Gmail poller, if it is configured.

    Gmail's OAuth flow is interactive, so the container cannot authenticate from
    scratch: a pre-generated token.pickle is injected base64-encoded via
    AK_GMAIL__TOKEN_B64 (see e2e/tests/scripts/gmail_login.py) and written to the
    configured token file before the adapter starts. When the Gmail env vars are
    absent the app simply runs without the Gmail integration.
    """
    token_b64 = os.environ.get("AK_GMAIL__TOKEN_B64")
    if not (os.environ.get("AK_GMAIL__CLIENT_ID") and os.environ.get("AK_GMAIL__CLIENT_SECRET") and token_b64):
        _log.info("Gmail credentials not configured - Gmail integration disabled")
        return None

    from agentkernel.core import Config
    from agentkernel.gmail import GmailInboundAdapter

    try:
        with open(Config.get().gmail.token_file, "wb") as token_file:
            token_file.write(base64.b64decode(token_b64))

        adapter = GmailInboundAdapter()
        adapter.authenticate()
        _log.info("Gmail poller configured")
        return PollerRunner(adapter)
    except Exception:
        _log.exception("Gmail integration failed to start - continuing without Gmail")
        return None


def _append_optional(handlers, name, env_var, construct):
    """Append an optional messaging handler.

    Skip it (with a log) when the credentials are absent, and degrade gracefully
    when they are only *partially* set: these adapters raise at construction time
    unless every required credential (e.g. access_token + phone_number_id +
    verify_token) is present, so a partial config must not crash the whole app and
    take the always-on Slack + Telegram handlers down with it.
    """
    if not os.environ.get(env_var):
        _log.info("%s credentials not configured - %s integration disabled", name, name)
        return
    try:
        handlers.append(WebhookRESTRequestHandler(construct()))
    except Exception:
        _log.exception("%s integration failed to construct - continuing without it", name)


def _handlers():
    handlers = [WebhookRESTRequestHandler(SlackInboundAdapter()), WebhookRESTRequestHandler(TelegramInboundAdapter())]

    def _whatsapp():
        from agentkernel.whatsapp import WhatsAppInboundAdapter

        return WhatsAppInboundAdapter()

    def _messenger():
        from agentkernel.messenger import MessengerInboundAdapter

        return MessengerInboundAdapter()

    def _instagram():
        from agentkernel.instagram import InstagramInboundAdapter

        return InstagramInboundAdapter()

    def _teams():
        from agentkernel.teams import TeamsInboundAdapter

        return TeamsInboundAdapter()

    _append_optional(handlers, "WhatsApp", "AK_WHATSAPP__ACCESS_TOKEN", _whatsapp)
    _append_optional(handlers, "Messenger", "AK_MESSENGER__ACCESS_TOKEN", _messenger)
    _append_optional(handlers, "Instagram", "AK_INSTAGRAM__ACCESS_TOKEN", _instagram)
    _append_optional(handlers, "Teams", "AK_TEAMS__APP_ID", _teams)
    return handlers


def main():
    poller = _maybe_gmail()
    IOHandler.run(handlers=_handlers(), pollers=[poller] if poller else None)


if __name__ == "__main__":
    main()
