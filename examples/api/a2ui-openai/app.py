"""An agent that answers with an interface, over plain REST, with history that replays as one.

Three things make this work, and only the first is A2UI-specific:

1. The agent is told the format, with a catalog of the components *this* application's frontend can
   draw. Agent Kernel ships no catalog, because one listing components a frontend cannot draw is
   worse than useless — the model emits them confidently and nothing renders.
2. The ``a2ui`` block in config.yaml is turned on. From there the framework labels the reply, and
   the REST response carries the payload as an object rather than a string.
3. ``ThreadRequestHandler`` replaces the pipeline's chat handler. The agent runs behind the queue
   (in-process here, since config.yaml declares no broker), and the handler records the user
   message before the request is enqueued; the runner records the reply on the other side. It also
   serves the two read routes the frontend's thread list uses. A recorded reply keeps its label, so
   a form that rendered live renders again on reload rather than coming back as a wall of JSON text.

Mounting is what enables threads; the ``thread`` block only picks the store. Note the one cost:
``user_id`` becomes **required** on this handler's chat routes, since a thread belongs to someone.

The handler's ``authoriser`` guards the **read** routes only: a thread is somebody's, so reading
one takes a token. The chat routes still take ``user_id`` from the body, which is why the frontend
sends both.

There is no post-hook here. That is the point: handling what comes back is two config keys.
"""

from typing import Optional

from agentkernel.auth import Authoriser
from agentkernel.openai import OpenAIModule
from agentkernel.pipeline import IOHandler
from agentkernel.thread import ThreadRequestHandler
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
  Field       {"label": "...", "value": "..."}      read-only: shows a value already recorded
  TextField   {"label": "...", "name": "..."}
  NumberField {"label": "...", "name": "..."}
  DateField   {"label": "...", "name": "..."}
  Select      {"label": "...", "name": "...", "options": ["..."]}
  Button      {"label": "..."}

For anything that does not need an interface — a greeting, a question, an explanation — reply with
ordinary prose. Most turns are prose. A surface built only from Card, Heading and Text carries
nothing a sentence does not: send the sentence instead.

When the user's message is a list of "field: value" pairs, that is a form you already showed coming
back submitted. Never show the editable form again — that reads as if the submission was lost.

  - everything needed is present -> confirm it with a surface: a Card holding a Heading and one
    Field per value you recorded. Use Field, never TextField; nothing here is being collected.
  - something required is missing -> reply with ordinary prose, naming only the field that is
    missing and asking for that one thing.

The confirmation is a surface rather than prose on purpose. A Field carries its value inside the
payload, so the values are part of what gets stored and come back on reload; a sentence of prose
reads the same today and is just a sentence tomorrow.
"""


class DemoAuthoriser(Authoriser):
    """
    Demo Authoriser protecting the thread read endpoints (GET /api/v1/threads*).

    A real subclass would validate the Bearer token against your own authentication
    provider (e.g. verify a JWT signature) and return the subject's user_id, or None
    to reject the request. Here a static token map stands in for that provider — one
    entry, since this example has one user and the sibling thread-openai example is
    where ownership scoping across users is demonstrated.
    """

    _TOKENS = {
        "demo-token": "demo-user",
    }

    def authorise(self, token: str) -> Optional[str]:
        return self._TOKENS.get(token)


expenses_agent = Agent(
    name="expenses",
    instructions=f"You help staff file expense claims.\n\n{CATALOG}",
    model="openai/gpt-4.1-mini",
)

OpenAIModule([expenses_agent])

if __name__ == "__main__":
    IOHandler.run(request_handler=ThreadRequestHandler(authoriser=DemoAuthoriser()))
