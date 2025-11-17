from __future__ import annotations

import logging
import threading
from contextvars import ContextVar
from typing import Any, Dict, Optional

from traceloop.sdk import Traceloop

from ...core import Runner
from ..base import BaseTrace

"""
Thread-safe context variable to store association properties per request.
"""
_association_properties: ContextVar[Dict[str, Any]] = ContextVar("association_properties", default={})

"""
Thread-safe context variable for span tracking
"""
_current_span: ContextVar[Optional[Any]] = ContextVar("current_span", default=None)


class TraceloopContext:
    """
    Thread-safe context manager wrapper for Traceloop.
    """

    _init_lock = threading.Lock()
    _initialized = False

    def __init__(self, app_name: Optional[str] = None, association_properties: Optional[Dict[str, Any]] = None):
        """
        Initialize Traceloop context.

        :param app_name: Application name for Traceloop
        :param association_properties: Custom properties to associate with this trace
        """
        self.app_name = app_name
        self.association_properties = association_properties or {}
        self._token = None

    @classmethod
    def initialize_global(cls, app_name: str, **kwargs):
        """
        Initialize Traceloop globally once (thread-safe).
        Should be called once at application startup.

        :param app_name: Application name
        **kwargs: Additional Traceloop.init() parameters
        """
        with cls._init_lock:
            if not cls._initialized:
                Traceloop.init(app_name=app_name, **kwargs)
                cls._initialized = True

    def __enter__(self):
        """
        Enter the context and set association properties for this request/thread.
        """
        self._token = _association_properties.set(self.association_properties.copy())
        if self.association_properties:
            Traceloop.set_association_properties(self.association_properties)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Exit the context and clean up association properties.
        """
        if self._token:
            _association_properties.reset(self._token)
        Traceloop.set_association_properties({})

        return False

    @staticmethod
    def set_association_properties(properties: Dict[str, Any]):
        """
        Update multiple association properties in the current context.
        :param properties: Dictionary of properties to add/update
        """
        props = _association_properties.get().copy()
        props.update(properties)
        _association_properties.set(props)
        Traceloop.set_association_properties(props)


class OpenLLMetry(BaseTrace):

    def __init__(self):
        """
        Initializes an OpenLLMetry instance.
        """
        self._log = logging.getLogger("ak.trace.openllmetry")

    def init(self):
        """
        Initializes the OpenLLMetry client.
        """
        TraceloopContext.initialize_global(app_name="AgentKernel")
        self._log.debug("OpenLLMetry initialized!")

    def openai(self) -> Runner:
        """
        Returns the OpenLLMetry OpenAI runner instance.
        """
        from .openai import OpenLLMetryOpenAIRunner

        return OpenLLMetryOpenAIRunner()

    def langgraph(self) -> Runner:
        """
        Returns the OpenLLMetry LangGraph runner instance.
        """
        from .langgraph import OpenLLMetryLangGraphRunner

        return OpenLLMetryLangGraphRunner()

    def crewai(self) -> Runner:
        """
        Returns the OpenLLMetry CrewAI runner instance.
        """
        from .crewai import OpenLLMetryCrewAIRunner

        return OpenLLMetryCrewAIRunner()

    def adk(self) -> Runner:
        """
        Returns the OpenLLMetry ADK runner instance.
        """
        from .adk import OpenLLMetryADKRunner

        return OpenLLMetryADKRunner()
