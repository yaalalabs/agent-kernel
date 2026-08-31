"""Sarasavi Power voice-call stack: WhatsApp Business Calling API <-> Gemini Live.

Layout mirrors the call path:
    whatsapp_ext.handler  routes `calls` webhook events here
    call_manager          owns per-call lifecycle (RINGING -> ... -> DONE)
    calls_api             Graph API signaling (pre_accept/accept/reject/terminate)
    bridge                aiortc WebRTC leg + Gemini Live audio pumps
    audio                 PCM16 resampling + playout buffering
    live_agent            Gemini Live config, voice tool schemas, tool executor
    summary               post-call memory shared with the text chat

Everything is use-case-local; ak-py and engine/ are untouched.
"""
