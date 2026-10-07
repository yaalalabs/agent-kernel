from operator import add
from pathlib import Path
from typing import Annotated, Any, Dict, Optional, TypedDict

from agentkernel.agui import AGUIRequestHandler
from agentkernel.api import RESTAPI
from agentkernel.auth import Authoriser
from agentkernel.langgraph import LangGraphModule
from agentkernel.openai import OpenAIModule, OpenAIToolBuilder
from agents import Agent
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

REFUNDS: Dict[str, float] = {"ORD-1001": 42.50, "ORD-1002": 980.00}


def issue_refund(order_id: str) -> str:
    """
    Refund an order. Requires human approval before it runs.

    :param order_id: The order to refund, e.g. "ORD-1001".
    :return: Confirmation of the refund.
    """
    amount = REFUNDS.get(order_id)
    if amount is None:
        return f"No order {order_id} found."
    return f"Refunded ${amount:.2f} for {order_id}."


def lookup_order(order_id: str) -> str:
    """
    Look up an order's refundable amount. Runs without approval.

    :param order_id: The order to look up.
    :return: The amount, or a not-found message.
    """
    amount = REFUNDS.get(order_id)
    return f"{order_id} is refundable for ${amount:.2f}." if amount else f"No order {order_id} found."


support_agent = Agent(
    name="support",
    instructions=(
        "You handle refund requests. Look the order up first, then issue the refund. "
        "If a refund was not carried out, say so plainly and do not claim it succeeded."
    ),
    # `needs_approval=True` is the whole of the human-in-the-loop setup, and the builder forwards it
    # to the SDK — so the tool above stays a plain function with nothing framework-specific on it.
    # The SDK stops before running that tool and hands the pending call back instead; Agent Kernel
    # turns that into a paused reply. Its body runs only once a human has approved. The two tools are
    # bound separately because the options apply to every function in a call.
    tools=OpenAIToolBuilder.bind([lookup_order]) + OpenAIToolBuilder.bind([issue_refund], needs_approval=True),
    model="openai/gpt-4.1-mini",
)

OpenAIModule([support_agent])


# --- LangGraph: the questions OpenAI cannot ask -------------------------------------------------
#
# The OpenAI SDK records an approval as a boolean — `RunState.approve()` takes no value — so a gated
# tool can only ever be approved or denied. Asking a human to *choose* something, or to type
# something, needs a framework whose pause carries a value back. LangGraph's `interrupt()` returns
# whatever the resume supplies, so both shapes work here.
#
# Asking costs nothing: `interrupt()` is plain Python and the two questions below reach no model. The
# `confirm` node that follows them does call one, so finishing the flow still needs an API key.


class RefundPlan(TypedDict):
    """The graph's state. `messages` is the channel Agent Kernel reads the reply from."""

    messages: Annotated[list, add]
    method: str
    note: str


def ask_preferences(state: RefundPlan) -> Dict[str, Any]:
    """Ask two questions in a row: one a choice, one free text.

    The second `interrupt()` is reached only once the first has an answer, so the run pauses twice
    and the client answers one question per turn. LangGraph **re-runs this node from the top** on
    resume — the first `interrupt()` then returns the stored answer instead of pausing again — which
    is why anything with a side effect belongs after the questions, never before them.
    """
    method = interrupt(
        {
            "question": "How should the refund be returned?",
            "options": ["Original card", "Store credit", "Bank transfer"],
        }
    )
    note = interrupt({"question": "Anything you want said to the customer? (free text)"})
    return {"method": method, "note": note}


def confirm(state: RefundPlan) -> Dict[str, Any]:
    """Write the confirmation, so the answers come back as streamed text.

    A node that merely returns a message produces no stream: `astream_events` streams *model*
    tokens, so a graph with no model call finishes silently over AG-UI. The REST surface would still
    return the text, which makes this an easy asymmetry to miss.
    """
    instruction = (
        f"In one short sentence, confirm to the customer that their refund will be returned via "
        f'{state["method"]}.' + (f' Work in this note from the agent: "{state["note"]}"' if state["note"] else "")
    )
    reply = ChatOpenAI(model="gpt-4.1-mini", temperature=0).invoke([SystemMessage(content=instruction)])
    return {"messages": [reply]}


_graph = StateGraph(RefundPlan)
_graph.add_node("ask_preferences", ask_preferences)
_graph.add_node("confirm", confirm)
_graph.add_edge(START, "ask_preferences")
_graph.add_edge("ask_preferences", "confirm")
_graph.add_edge("confirm", END)

LangGraphModule([_graph.compile(name="planner")])


class DemoAuthoriser(Authoriser):
    """Maps a static demo token to a user id. AG-UI has no anonymous mode."""

    _TOKENS = {"demo-token": "demo-user"}

    def authorise(self, token: str) -> Optional[str]:
        """Resolve a bearer token to a user id.

        :param token: Bearer token from the Authorization header.
        :return: The acting user id, or None to reject the request.
        """
        return self._TOKENS.get(token)


DIST = Path(__file__).parent / "frontend" / "dist"

BUILD_HINT = (
    "<h1>Frontend not built</h1>"
    "<p>The approval console is a Vite app. From <code>frontend/</code> run "
    "<code>npm install &amp;&amp; npm run dev</code> and open "
    '<a href="http://localhost:5173">http://localhost:5173</a> — it proxies <code>/agui</code> to this process.</p>'
    "<p>To serve it from this origin instead, run <code>npm run build</code> there; this page then loads "
    "<code>frontend/dist</code>.</p>"
    "<p>The AG-UI routes under <code>/agui</code> and the REST route at <code>/api/v1/chat</code> work "
    "regardless — this page is only the demo UI.</p>"
)

ui_router = APIRouter()


@ui_router.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """Serve the built console, or a hint when frontend/dist is missing."""
    entry = DIST / "index.html"
    if not entry.is_file():
        return HTMLResponse(BUILD_HINT, status_code=503)
    return HTMLResponse(entry.read_text())


@ui_router.get("/assets/{filename}", include_in_schema=False)
def asset(filename: str) -> FileResponse:
    """Serve a file from frontend/dist/assets by exact name."""
    root = DIST / "assets"
    match = next((p for p in root.iterdir() if p.name == filename and p.is_file()), None) if root.is_dir() else None
    if match is None:
        raise HTTPException(status_code=404, detail="No such asset")
    return FileResponse(match)


RESTAPI.add(ui_router)

if __name__ == "__main__":
    # `handlers=` replaces the defaults rather than adding to them, so the REST handler is listed
    # explicitly. Both surfaces then serve the same session, and the same pause can be answered from
    # either one:
    #   AG-UI  POST /agui/support   — streamed, ends with an interrupt outcome
    #   REST   POST /api/v1/chat    — answers 202 with status: "PAUSED"
    RESTAPI.run(handlers=[*RESTAPI.get_default_handlers(), AGUIRequestHandler(authoriser=DemoAuthoriser())])
