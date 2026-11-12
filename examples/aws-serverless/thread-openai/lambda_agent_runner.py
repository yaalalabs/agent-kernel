"""Agent-runner Lambda: consumes the Input Queue, runs the agent, sends to the Output Queue.

A chat message the request handler recorded carries the thread marker; after sending the reply,
ServerlessAgentRunner records it in the same thread. The runner needs the same `thread` block as the
request handler, to know which store to write to.
"""

from agentkernel.aws import ServerlessAgentRunner

import agent  # noqa: F401  (registers the agent)

handler = ServerlessAgentRunner.handle
