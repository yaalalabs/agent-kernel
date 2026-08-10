"""
Conversation Thread Support integration.

Packages the thread capability the way messaging integrations are packaged: the
handler owns its routes (chat with recording, plus thread read routes) and its
logic (ThreadRecorder), and applications enable the feature by mounting
AgentThreadRequestHandler.
"""

from .recorder import ThreadRecorder
from .thread_chat import AgentThreadRequestHandler, ThreadRESTRequestHandler
