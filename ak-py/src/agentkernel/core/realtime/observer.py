from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Literal, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from ..base import Agent, Session


class RealtimeEvent(BaseModel):
    """Something that happened in a live realtime call (``execution.mode: realtime``), as a ``RealtimeObserver`` sees it.

    ``connected`` is a new model connection, which starts at the call's first agent and remembers nothing;
    ``reconnected`` is the adapter replacing a lost model socket within the connection, replaying the conversation.
    """

    type: Literal["connected", "caller_said", "edge_text", "agent_said", "agent_changed", "reconnected", "disconnected"]
    session_id: str
    agent: Optional[str] = None
    text: str = ""
    interrupted: bool = False
    at: float = Field(default_factory=time.time)


class RealtimeObserver(ABC):
    """Watches the live realtime calls of this process, registered with ``RealtimeCall.observe``; it cannot change them.

    Events reach it in order, one at a time, off the audio path; one that raises is logged and the next observer runs.
    """

    @abstractmethod
    async def on_event(self, session: "Session", agent: "Agent", event: RealtimeEvent) -> None:
        """Called for every event of every live call; ``agent`` is the agent the call started with."""
        raise NotImplementedError

    @abstractmethod
    def name(self) -> str:
        """Returns the name of the realtime observer."""
        raise NotImplementedError
