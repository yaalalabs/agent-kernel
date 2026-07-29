"""First-party sandbox providers.

Each provider lives in its own module and is imported lazily by
``SandboxProviderFactory`` when a profile selects it — this package has no eager
imports so optional SDK extras (``sandbox-docker``, ``e2b``, ``daytona``,
``kubernetes``, ``aws``) stay optional.
"""
