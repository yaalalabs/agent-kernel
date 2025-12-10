import logging
import traceback
from abc import ABC, abstractmethod
from http import HTTPStatus
from typing import List, Literal, Optional, Union

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from agentkernel.core.model import (
    AgentReplyImage,
    AgentReplyText,
    AgentRequestAny,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
)

from ..core import AgentService, GlobalRuntime


class RESTRequestHandler(ABC):
    @abstractmethod
    def get_router(self) -> APIRouter:
        """
        Returns the APIRouter instance which has configured routes
        E.g.:
        - GET /health: Health check
        - GET /agents: List available agents

        router = APIRouter()

        @router.get("/health")
        def health():
            return {"status": "ok"}

        @router.get("/agents")
        def list_agents():
            return {"agents": list(GlobalRuntime.instance().agents().keys())}

        """
        pass


class AgentRESTRequestHandler(RESTRequestHandler):
    """
    API routers that expose endpoints to interact with Agent Kernel.
    Endpoints:
    - GET /health: Health check
    - GET /agents: List available agents
    - POST /run: Run an agent with a prompt
      Payload JSON: { "prompt": str, "agent": str | null, "session_id": str | null }
    """

    def __init__(self):
        self._log = logging.getLogger("ak.api.agent")

    class FileData(BaseModel):
        """Represents a file attachment"""

        file_data: str  # base64 encoded string or URL
        name: str
        mime_type: Optional[str] = None

    class ImageData(BaseModel):
        """Represents an image attachment"""

        image_data: str  # base64 encoded string
        name: str
        mime_type: Optional[str] = None

    class RunRequest(BaseModel):
        model_config = ConfigDict(extra="allow")

        prompt: str
        agent: Optional[str] = None
        session_id: Optional[str] = None
        files: Optional[List["AgentRESTRequestHandler.FileData"]] = None
        images: Optional[List["AgentRESTRequestHandler.ImageData"]] = None

    def get_router(self) -> APIRouter:
        """
        Returns the APIRouter instance.
        """

        router = APIRouter()

        @router.get("/health")
        def health():
            return {"status": "ok"}

        @router.get("/agents")
        def list_agents():
            return {"agents": list(GlobalRuntime.instance().agents().keys())}

        @router.post("/run")
        async def run(body: AgentRESTRequestHandler.RunRequest):
            return await self.run(body)

        return router

    async def run(self, req: RunRequest):
        """
        Async method to run the agent.
        :param req: Request object containing the prompt, optional agent name, attachments, images, and additional properties.
        """
        requests = []
        requests.append(AgentRequestText(text=req.prompt))
        service = None
        try:
            # Process attachments (documents, PDFs, CSVs, etc.)
            if req.files:
                for file in req.files:
                    self._log.debug(f"Adding file attachment: {file.name}")
                    if not file.file_data.startswith(("http://", "https://", "data:")) and not file.mime_type:
                            raise ValueError("mime_type is missing for file input, either in the base64 or explicitly")
                    requests.append(
                        AgentRequestFile(
                            file_data=file.file_data,
                            name=file.name,
                            mime_type=file.mime_type if file.mime_type else None,
                        )
                    )

            # Process images (JPEG, PNG, etc.)
            if req.images:
                for image in req.images:
                    self._log.debug(f"Adding image: {image.name}")
                    if not image.image_data.startswith(("http://", "https://", "data:")) and not image.mime_type:
                            raise ValueError("mime_type is missing for image input, either in the base64 or explicitly")
                    requests.append(
                        AgentRequestImage(
                            image_data=image.image_data,
                            name=image.name,
                            mime_type=image.mime_type if image.mime_type else None,
                        )
                    )

            # Pack additional properties into AgentRequestAny
            known_fields = {"prompt", "agent", "session_id", "attachments", "images"}
            for key, value in req.model_dump().items():
                if key not in known_fields:
                    self._log.debug(f"Adding additional context: {key}={value}")
                    requests.append(AgentRequestAny(name=key, content=value))
            service = AgentService()

            
            service.select(req.session_id, req.agent)
            if not service.agent:
                raise ValueError("No agent available")

            result = await service.run_multi(requests=requests)
            self._log.debug(f"Result: {result}")

            return {
                "result": (
                    str(result)
                    if isinstance(result, (AgentReplyText, AgentReplyImage))
                    else "Non textual result received"
                ),  # sending image is not supported at the moment
                "session_id": service.get_response_session_id(req.session_id),
            }

        except HTTPException:
            raise
        except ValueError as e:
            self._log.error(f"POST /run error: {e}\n{traceback.format_exc()}")
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail={
                    "error": str(e),
                    "session_id": service.get_response_session_id(req.session_id) if service is not None else req.session_id,
                },
            )
        except Exception as e:
            self._log.error(f"POST /run error: {e}\n{traceback.format_exc()}")
            raise HTTPException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail={
                    "error": str(e),
                    "session_id": service.get_response_session_id(None)  if service is not None else req.session_id,
                },
            )
