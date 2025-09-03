import logging
import traceback
from http import HTTPStatus
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..core import AgentService

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    force=True
)

app = FastAPI(title="Agent Kernel REST API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


class RunRequest(BaseModel):
    prompt: str
    agent: Optional[str] = None
    session_id: Optional[str] = None


class RESTRequestHandler(AgentService):
    """
    A simple REST API handler that exposes endpoints to interact with Agent Kernel.
    Endpoints:
    - GET /health: Health check
    - GET /agents: List available agents
    - POST /run: Run an agent with a prompt
      Payload JSON: { "prompt": str, "agent": str | null, "session_id": str | null }
    """

    _log = logging.getLogger("ak.api.restapi")

    @classmethod
    async def run(cls, req: RunRequest):
        """
        Async method to run the agent.
        :param req: Request an object containing the prompt and optional agent name.
        """
        try:
            cls._select(req.session_id, req.agent)
            if not cls._agent:
                cls._select(req.session_id)
                if not cls._agent:
                    raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail={
                        "error": "No agent available",
                        "session_id": cls._get_response_session_id(req.session_id)
                    })
            result = await cls._run_agent(req.prompt)

            if hasattr(result, 'raw'):
                payload = {
                    "result": str(result.raw),
                    "session_id": cls._get_response_session_id(req.session_id)
                }
            else:
                payload = {
                    "result": result,
                    "session_id": cls._get_response_session_id(req.session_id)
                }
            return payload
        except HTTPException:
            raise
        except Exception as e:
            cls._log.error(f"POST /run error: {e}\n{traceback.format_exc()}")
            raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail={
                "error": str(e),
                "session_id": cls._get_response_session_id(None)
            })


# FastAPI routes
@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/agents")
def list_agents():
    return {"agents": list(RESTRequestHandler.get_runtime().agents().keys())}


@app.post("/run")
async def run(req: RunRequest):
    return await RESTRequestHandler.run(req)


class RESTAPI:
    """
    Handles the initialization and running of the REST API server.
    Provides functionality for starting an HTTP server for the Agent Kernel REST API.
    This class encapsulates the necessary setup and invocation of the server,
    including logging the server address details and starting the server using
    Uvicorn.
    """

    @classmethod
    def run(cls, host: str = "0.0.0.0", port: int = 8000):
        """
        Starts the REST API server.
        :param host: Hostname or IP address to bind the server to.
        :param port: Port number to bind the server to.
        """
        log = logging.getLogger("ak.rest.server")
        log.info(f"Agent Kernel REST API listening on http://{host}:{port}")
        uvicorn.run("ak.api.restapi:app", host=host, port=port, reload=False)
