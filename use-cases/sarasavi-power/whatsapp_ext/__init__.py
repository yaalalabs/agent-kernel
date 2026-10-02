"""Sarasavi Power WhatsApp channel extensions.

Everything Agent Kernel's stock WhatsApp handler does not do yet lives here:
voice-note handling (inbound audio -> Gemini, outbound TTS voice replies) and,
via the ``voice`` package, WhatsApp Business Calling API routing. No ak-py edits.
"""

from .handler import SarasaviWhatsAppHandler

__all__ = ["SarasaviWhatsAppHandler"]
