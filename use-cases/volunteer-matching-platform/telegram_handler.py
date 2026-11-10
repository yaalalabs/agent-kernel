"""Telegram formatting.

agentkernel's AgentTelegramRequestHandler always sends plain text (its internal
_send_message calls never pass parse_mode), so an agent reply's **bold**/*italic* markdown
shows up as literal asterisks in the chat. This subclass overrides _send_message — the one
method every outgoing message funnels through, including /start, /help, and the error
fallbacks — to render that markdown as Telegram's real HTML formatting instead.

HTML over Telegram's own Markdown/MarkdownV2 parse modes deliberately: those require
escaping many special characters (_*[]()~`>#+-=|{}.!) in plain text or the whole message
fails to send ("can't parse entities") — a real risk with arbitrary LLM-generated text. HTML
only requires escaping &, <, > (done unconditionally below, before any tags are added), so a
malformed send is far less likely.
"""

import html
import re

from agentkernel.telegram import AgentTelegramRequestHandler


def markdown_to_telegram_html(text: str) -> str:
    """Convert **bold**/*italic*/_italic_/`code` into Telegram's supported HTML subset.

    Escapes the raw text first, then substitutes in real tags — so any literal <, >, or &
    in the agent's own text can never be misread as markup.
    """
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", escaped)
    escaped = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"<i>\1</i>", escaped)
    return escaped


class FormattedTelegramRequestHandler(AgentTelegramRequestHandler):
    """AgentTelegramRequestHandler with markdown-to-HTML formatting on every outgoing message."""

    async def _send_message(self, chat_id, text, parse_mode=None, reply_markup=None):
        await super()._send_message(
            chat_id, markdown_to_telegram_html(text), parse_mode="HTML", reply_markup=reply_markup
        )
