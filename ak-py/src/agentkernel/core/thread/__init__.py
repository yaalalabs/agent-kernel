"""
Conversation Thread Support for Agent Kernel.

This package provides:
- Thread / ThreadMessage / ThreadAttachment models
- ThreadStore storage abstraction with pluggable backends
- ConversationThreadManager service façade
- Authoriser pluggable base class for thread route authorization
"""

from .authoriser import Authoriser
from .manager import ConversationThreadManager
from .model import MessagePage, Thread, ThreadAttachment, ThreadMessage, ThreadPage
from .store import ThreadStore, ThreadStoreBuilder
