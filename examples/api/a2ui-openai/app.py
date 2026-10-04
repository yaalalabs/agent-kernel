"""An agent that answers with an interface, over plain REST.

Two things make this work, and only the first is A2UI-specific:

1. The agent is told the format, with a catalog of the components *this* application's frontend can
   draw. Agent Kernel ships no catalog, because one listing components a frontend cannot draw is
   worse than useless — the model emits them confidently and nothing renders.
2. The ``a2ui`` block in config.yaml is turned on. From there the framework labels the reply, and
   the REST response carries the payload as an object rather than a string.

There is no post-hook here. That is the point: handling what comes back is two config keys.
"""

from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agents import Agent

CATALOG = """
You may answer with a user interface instead of prose when the answer is better shown than
described — a form to fill in, a table of results, a confirmation to approve.

To do so, reply with ONLY a JSON object in the A2UI format, and nothing else — no prose before or
after it, no markdown fence:

{
  "version": "v1.0",
  "createSurface": {
    "surfaceId": "<a short name for this surface>",
    "components": [
      {"id": "root", "component": {"Card": {"children": ["<child ids, in order>"]}}},
      ...
    ]
  }
}

One component MUST have "id": "root". The components this client can draw, and nothing else:

  Card        {"children": [ids]}
  Text        {"text": "..."}
  Heading     {"text": "..."}
  TextField   {"label": "...", "name": "..."}
  NumberField {"label": "...", "name": "..."}
  DateField   {"label": "...", "name": "..."}
  Select      {"label": "...", "name": "...", "options": ["..."]}
  Button      {"label": "..."}

For anything that does not need an interface — a greeting, a question, an explanation — reply with
ordinary prose. Most turns are prose.

When the user's message is a list of "field: value" pairs, that is a form you already showed coming
back submitted. Do NOT show the form again. Reply with ordinary prose instead:

  - everything needed is present -> confirm it in one short sentence, naming the values recorded
  - something required is missing -> say which field, and ask only for that

Showing the same form twice reads as if the submission was lost, so prefer prose here even when the
answer is short.
"""

expenses_agent = Agent(
    name="expenses",
    instructions=f"You help staff file expense claims.\n\n{CATALOG}",
    model="openai/gpt-4.1-mini",
)

OpenAIModule([expenses_agent])

if __name__ == "__main__":
    RESTAPI.run()
