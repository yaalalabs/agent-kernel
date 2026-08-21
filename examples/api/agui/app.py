from pathlib import Path
from typing import Optional

from agentkernel.agui import AGUIRequestHandler
from agentkernel.api import RESTAPI
from agentkernel.auth import Authoriser
from agentkernel.openai import OpenAIModule
from agents import Agent
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

planner_agent = Agent(
    name="planner",
    instructions="You help the user keep a short task list. The list lives in the shared AG-UI state "
    "under the key 'tasks', as a list of {title, done} objects.\n"
    "Whenever the user adds, completes, renames or removes a task, read the current state, then write "
    "the full new list back with update_agui_state. The user only sees a change once you have written "
    "it — describing it in your reply changes nothing on their screen.\n"
    "When the user asks about something they never told you in this conversation — their local time, "
    "the page they are on, a preference — call get_agui_context and get_forwarded_props first. Do not "
    "say you do not know until you have looked.\n"
    "Keep replies to one short sentence.",
)


class DemoAuthoriser(Authoriser):
    """Maps a static demo token to a user id. AG-UI has no anonymous mode."""

    _TOKENS = {"demo-token": "demo-user"}

    def authorise(self, token: str) -> Optional[str]:
        return self._TOKENS.get(token)


OpenAIModule([planner_agent])

DIST = Path(__file__).parent / "frontend" / "dist"

BUILD_HINT = (
    "<h1>Frontend not built</h1>"
    "<p>The demo UI is a Vite app. From <code>frontend/</code> run <code>npm install &amp;&amp; npm run dev</code> "
    'and open <a href="http://localhost:5173">http://localhost:5173</a> — it proxies <code>/agui</code> to this process.</p>'
    "<p>To serve the UI from this origin instead, run <code>npm run build</code> there; this page then loads <code>frontend/dist</code>.</p>"
    "<p>The AG-UI routes under <code>/agui</code> work regardless — this page is only the demo UI.</p>"
)

ui_router = APIRouter()


@ui_router.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """Serve the built UI, or a hint if frontend/dist is missing."""
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


def runner() -> None:
    """Mount AG-UI and start the API. Referenced by the Dockerfile."""
    RESTAPI.run(handlers=[AGUIRequestHandler(authoriser=DemoAuthoriser())])


if __name__ == "__main__":
    runner()
