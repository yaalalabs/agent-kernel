"""A2UI labelling capability.

Supplies the one thing about A2UI that is the same for every application — its media type — and
nothing else. No catalog, no prompt injection, no validation, no dependency on the A2UI SDK: all of
those have to match a particular frontend, so they stay with the application.
"""

from .hook import A2UIPostHook, A2UIPostHookFactory, NoOpA2UIPostHook

__all__ = ["A2UIPostHook", "A2UIPostHookFactory", "NoOpA2UIPostHook"]
