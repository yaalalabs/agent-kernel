"""Credentials (#603): the inbound credential of a run, kept encrypted for the run's tools.

Nothing is imported here: the shared stores need optional extras (``redis``, ``valkey``, ``aws``), and the
cipher the ``auth`` extra. Import the module you need, or a name from ``agentkernel.identity``.
"""
