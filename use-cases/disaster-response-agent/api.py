"""Run the Disaster Response & Resource Coordination Agent as a REST API via Agent Kernel.

Usage:
    python api.py

Then, e.g.:
    curl -X POST http://localhost:8000/api/v1/chat \\
      -H "Content-Type: application/json" \\
      -d '{"prompt": "Need drinking water in Galle", "session_id": "field-worker-1", "agent": "intake_agent"}'

See README.md for more example requests (offers, status queries, follow-up merges).
"""

from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule

from agent import AGENTS

OpenAIModule(AGENTS)

if __name__ == "__main__":
    RESTAPI.run()
