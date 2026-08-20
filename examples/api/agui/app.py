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
    """
    Demo Authoriser protecting the AG-UI routes.

    A real subclass would validate the Bearer token against your own authentication provider
    (e.g. verify a JWT signature) and return the subject's user_id, or None to reject. Here a
    static token map stands in for that provider. Unlike the thread read routes, AG-UI has no
    open mode: AGUIRequestHandler refuses to construct without an Authoriser or an AuthValidator.
    """

    _TOKENS = {"demo-token": "demo-user"}

    def authorise(self, token: str) -> Optional[str]:
        return self._TOKENS.get(token)


OpenAIModule([planner_agent])

# Serves the built React app in frontend/dist. api.custom_router_prefix is set to "" in config.yaml,
# so the frontend and the AG-UI routes share one origin and the browser needs no CORS handling.
#
# Both routes read from disk per request, so rebuilding the frontend needs no server restart — Vite
# emits a new content hash in the asset filenames on every build, which a route registered per file at
# startup would then 404.
DIST = Path(__file__).parent / "frontend" / "dist"

BUILD_HINT = (
    "<h1>Frontend not built</h1>"
    "<p>Run <code>./build.sh</code>, or <code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code>.</p>"
    "<p>The AG-UI routes under <code>/agui</code> work regardless — this page is only the demo UI.</p>"
)

ui_router = APIRouter()


@ui_router.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """Serve the built single-page app, or an explanation of how to build it."""
    entry = DIST / "index.html"
    if not entry.is_file():
        return HTMLResponse(BUILD_HINT, status_code=503)
    return HTMLResponse(entry.read_text())


@ui_router.get("/assets/{filename}", include_in_schema=False)
def asset(filename: str) -> FileResponse:
    """Serve one of Vite's built assets.

    The requested name is matched against the directory's own entries rather than joined onto it, so
    the request never contributes a path segment — the servable set is exactly what is on disk, and a
    traversal attempt has nothing to traverse.
    """
    root = DIST / "assets"
    match = next((p for p in root.iterdir() if p.name == filename and p.is_file()), None) if root.is_dir() else None
    if match is None:
        raise HTTPException(status_code=404, detail="No such asset")
    return FileResponse(match)


RESTAPI.add(ui_router)


def runner() -> None:
    """Entry point referenced by the Dockerfile.

    Mounting AGUIRequestHandler is what enables AG-UI; the `agui` block in config.yaml only
    parameterizes it. The standard chat routes are not mounted here — this app serves AG-UI only.
    """
    RESTAPI.run(handlers=[AGUIRequestHandler(authoriser=DemoAuthoriser())])


if __name__ == "__main__":
    runner()
