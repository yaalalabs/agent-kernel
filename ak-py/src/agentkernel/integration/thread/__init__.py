"""
Conversation Thread Support integration.

This package owns the thread capability end to end, the way messaging
integrations own theirs: the handler and its routes (chat with recording, plus
thread read routes), the recording logic (ThreadRecorder), and the thread
domain itself (ConversationThreadManager, models, naming, pluggable stores).
Applications enable the feature by mounting AgentThreadRequestHandler; the
'thread' config block only parameterizes the store backend and naming.
"""

from .authoriser import Authoriser
from .manager import ConversationThreadManager
from .model import MessagePage, Thread, ThreadAttachment, ThreadMessage, ThreadPage
from .naming import ThreadNamingStrategy
from .recorder import ThreadRecorder
from .store import ThreadStore, ThreadStoreBuilder
from .thread_chat import AgentThreadRequestHandler, ThreadRESTRequestHandler
