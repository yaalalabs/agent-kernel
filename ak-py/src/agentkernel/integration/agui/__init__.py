"""
AG-UI protocol integration.

This package owns the AG-UI surface end to end, the way the thread and messaging integrations own
theirs: the routes and run lifecycle (AGUIRequestHandler), the inbound mapping and its trust
boundary (run_input), and the outbound event translation (mapping). Applications enable AG-UI by
mounting AGUIRequestHandler; the 'agui' config block only parameterizes it.

The agent-facing half lives in `core/client_state.py` — a system tool is attached at agent wrap time
by `SystemToolFactory`, and core owns these because they are core capabilities, not because of an import
constraint (`SystemToolFactory.get_all()` already reaches outside core for the sandbox branch). Its
contents are named for AG-UI like everything else; only the filename is surface-neutral, so `core/`
carries no integration name in its listing.
"""

from .handler import AGUIRequestHandler
