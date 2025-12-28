"""
Shared multimodal hooks for all Agent Kernel frameworks.

This module provides framework-agnostic hooks for multimodal conversation memory,

Architecture:
- MultimodalContextHook (Pre-hook): Loads previous attachments from cache and 
  injects them into the current request so the model has context.
- MultimodalMemoryHook (Post-hook): Saves new attachments to non-volatile cache
  (Redis/DynamoDB) for persistence across requests.
- MultimodalModuleMixin: Mixin class for framework modules to auto-register hooks.

Example flow:
  User: [sends image] "What's in this photo?"
  → Post-hook saves image to cache
  Bot: "I see a red car."
  
  User: "What color is the house in the background?"
  → Pre-hook loads previous image and injects it
  → Model receives: [previous image] + "What color is the house..."
  Bot: "The house appears to be white."

Configuration via environment variables:
  AK_OPENAI__MULTIMODAL_MEMORY=true    # Enable/disable (default: true)
  AK_OPENAI__MAX_ATTACHMENTS=5         # Max attachments in context
  AK_OPENAI__ATTACHMENT_TTL=604800     # Expiry in seconds (1 week)
"""

import logging
import time
from typing import TYPE_CHECKING

from .hooks import Prehook, Posthook
from .model import AgentRequestImage, AgentRequestFile

if TYPE_CHECKING:
    from .session import Session
    from .base import Agent
    from .model import AgentRequest, AgentReply

# Default: keep last 5 attachments in context (configurable)
DEFAULT_MAX_ATTACHMENTS = 5
# Default: attachments expire after 1 week (604800 seconds) - matches session TTL
DEFAULT_ATTACHMENT_TTL = 604800


class MultimodalContextHook(Prehook):
    """
    Pre-hook that loads previous images/files from non-volatile cache and injects 
    
    """

    def __init__(self, max_attachments: int = DEFAULT_MAX_ATTACHMENTS, ttl_seconds: int = DEFAULT_ATTACHMENT_TTL):
        """
        Initialize the context hook.
        
        :param max_attachments: Maximum number of recent attachments to inject (default: 5)
        :param ttl_seconds: Time-to-live for attachments in seconds (default: 604800 = 1 week)
        """
        self._log = logging.getLogger("ak.hooks.multimodal_context")
        self._max_attachments = max_attachments
        self._ttl_seconds = ttl_seconds

    async def on_run(self, session: "Session", agent: "Agent", requests: list["AgentRequest"]) -> list["AgentRequest"]:
        """
        Load previous attachments from cache and inject into the request.

        :param session: The current session
        :param agent: The agent instance
        :param requests: List of current agent requests
        :return: Modified requests with previous attachments injected
        """
        if not session:
            return requests

        nv_cache = session.get_non_volatile_cache()
        current_time = time.time()
        
        # Collect all stored attachments
        attachments = []
        keys_to_check = nv_cache.keys() if hasattr(nv_cache, 'keys') else []
        
        if not keys_to_check:
            # Try to retrieve using the index if available
            index_data = nv_cache.get("_attachment_index")
            if index_data:
                keys_to_check = index_data.get("keys", [])
        
        for key in keys_to_check:
            if not (key.startswith("attachment_image_") or key.startswith("attachment_file_")):
                continue
                
            data = nv_cache.get(key)
            if not data:
                continue
                
            # Check TTL
            timestamp = data.get("timestamp", 0)
            if current_time - timestamp > self._ttl_seconds:
                # Expired, skip (could also delete here)
                self._log.debug(f"Skipping expired attachment: {key}")
                continue
                
            attachments.append({
                "key": key,
                "data": data,
                "timestamp": timestamp
            })
        
        if not attachments:
            return requests
            
        # Sort by timestamp and limit
        # Use secondary sort by key for consistent ordering when timestamps match
        attachments.sort(key=lambda x: (x["timestamp"], x["key"]))
        attachments = attachments[-self._max_attachments:]
        
        # Inject attachments at the beginning of requests
        injected_requests = []
        for att in attachments:
            data = att["data"]
            att_type = data.get("type")
            
            if att_type == "image":
                img_req = AgentRequestImage(
                    image_data=data.get("data"),
                    mime_type=data.get("mime_type"),
                    name=data.get("name", "previous_image")
                )
                # Mark as injected so post-hook doesn't re-save it
                img_req._injected = True
                injected_requests.append(img_req)
            elif att_type == "file":
                file_req = AgentRequestFile(
                    file_data=data.get("data"),
                    mime_type=data.get("mime_type"),
                    name=data.get("name", "previous_file")
                )
                # Mark as injected so post-hook doesn't re-save it
                file_req._injected = True
                injected_requests.append(file_req)
        
        if injected_requests:
            self._log.info(f"Injected {len(injected_requests)} previous attachment(s) into context")
            # Prepend previous attachments, then add current requests
            return injected_requests + list(requests)
        
        return requests

    def name(self) -> str:
        """Return hook name"""
        return "MultimodalContextHook"


class MultimodalMemoryHook(Posthook):
    """
    Post-hook that stores images and files in non-volatile cache after agent processes them.
    
    This hook ensures multimodal attachments are persisted in the session cache
    (Redis or DynamoDB) so they're available in subsequent requests via MultimodalContextHook.
    
    Works with all frameworks: OpenAI, ADK, LangGraph, CrewAI
    """

    def __init__(self, max_attachments: int = DEFAULT_MAX_ATTACHMENTS):
        """
        Initialize the memory hook.
        
        :param max_attachments: Maximum number of attachments to keep in cache (default: 5)
        """
        self._log = logging.getLogger("ak.hooks.multimodal_memory")
        self._max_attachments = max_attachments

    async def on_run(
        self, 
        session: "Session", 
        requests: list["AgentRequest"], 
        agent: "Agent", 
        agent_reply: "AgentReply"
    ) -> "AgentReply":
        """
        Save multimodal attachments to non-volatile cache after agent processes them.

        :param session: The current session
        :param requests: List of agent requests (may contain AgentRequestImage/AgentRequestFile)
        :param agent: The agent instance
        :param agent_reply: The agent's reply
        :return: The agent_reply unchanged
        """
        if not session:
            return agent_reply

        nv_cache = session.get_non_volatile_cache()
        timestamp = time.time()
        attachment_count = 0
        new_keys = []

        # Store each image/file with timestamp
        for i, req in enumerate(requests):
            if isinstance(req, AgentRequestImage):
                # Skip if this is an injected previous attachment
                if getattr(req, '_injected', False):
                    continue
                    
                cache_key = f"attachment_image_{timestamp}_{i}"
                nv_cache.set(cache_key, {
                    "type": "image",
                    "data": req.image_data,
                    "mime_type": req.mime_type,
                    "name": getattr(req, 'name', None),
                    "timestamp": timestamp
                })
                new_keys.append(cache_key)
                self._log.debug(f"Stored image to cache: {cache_key}")
                attachment_count += 1

            elif isinstance(req, AgentRequestFile):
                # Skip if this is an injected previous attachment
                if getattr(req, '_injected', False):
                    continue
                    
                cache_key = f"attachment_file_{timestamp}_{i}"
                nv_cache.set(cache_key, {
                    "type": "file",
                    "data": req.file_data,
                    "mime_type": req.mime_type,
                    "name": req.name,
                    "timestamp": timestamp
                })
                new_keys.append(cache_key)
                self._log.debug(f"Stored file to cache: {cache_key}")
                attachment_count += 1

        # Update attachment index for cache implementations without keys() method
        if new_keys:
            index_data = nv_cache.get("_attachment_index") or {"keys": []}
            index_data["keys"].extend(new_keys)
            # Keep only recent keys
            index_data["keys"] = index_data["keys"][-self._max_attachments * 2:]
            nv_cache.set("_attachment_index", index_data)

        if attachment_count > 0:
            self._log.info(f"Stored {attachment_count} multimodal attachment(s) to non-volatile cache")

        return agent_reply

    def name(self) -> str:
        """Return hook name"""
        return "MultimodalMemoryHook"


class MultimodalModuleMixin:
    """
    Mixin class that provides multimodal memory hook registration for framework modules.
    
    Usage:
        class OpenAIModule(MultimodalModuleMixin, Module):
            def __init__(self, agents, runner=None):
                super().__init__()
                # ... setup ...
                self._register_multimodal_hooks(agents)
    
    Configuration is read from AKConfig.openai settings:
        - multimodal_memory: bool (default: True)
        - max_attachments: int (default: 5)
        - attachment_ttl: int (default: 604800 = 1 week)
    """

    def _register_multimodal_hooks(self, agents: list) -> None:
        """
        Register multimodal memory hooks for all agents if enabled in config.
        
        :param agents: List of agents (framework-specific agent objects)
        """
        from .config import AKConfig
        from .runtime import GlobalRuntime
        
        config = AKConfig.get().multimodal
        if not config.enabled:
            return

            
        runtime = GlobalRuntime.instance()
        
        # Create hooks with config values
        context_hook = MultimodalContextHook(
            max_attachments=config.max_attachments,
            ttl_seconds=config.attachment_ttl
        )
        memory_hook = MultimodalMemoryHook(
            max_attachments=config.max_attachments
        )
        
        # Register hooks for each agent
        for agent in agents:
            # Get agent name - handle different agent object types
            agent_name = getattr(agent, 'name', None) or str(agent)
            
            # Get existing hooks and append
            existing_pre_hooks = runtime.get_pre_hooks(agent_name)
            existing_post_hooks = runtime.get_post_hooks(agent_name)
            
            # Add our hooks
            runtime.register_pre_hooks(agent_name, existing_pre_hooks + [context_hook])
            runtime.register_post_hooks(agent_name, existing_post_hooks + [memory_hook])