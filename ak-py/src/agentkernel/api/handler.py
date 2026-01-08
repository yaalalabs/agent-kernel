import base64
import logging
import traceback
from abc import ABC, abstractmethod
from http import HTTPStatus
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict

from agentkernel.core.model import (
    AgentReplyImage,
    AgentReplyText,
    AgentRequestAny,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
)

from ..core import AgentService, Config
from ..core.runtime import Runtime


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
            from ..core.runtime import Runtime
            return {"agents": list(Runtime.current().agents().keys())}

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
        self._max_file_size = Config.get().api.max_file_size

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
            return {"agents": list(Runtime.current().agents().keys())}

        @router.post("/run")
        async def run(body: AgentRESTRequestHandler.RunRequest):
            return await self.run(body)

        @router.post("/run-multipart")
        async def run_multipart(
            prompt: str = Form(...),
            agent: Optional[str] = Form(None),
            session_id: Optional[str] = Form(None),
            files: Optional[List[UploadFile]] = File(None),
            images: Optional[List[UploadFile]] = File(None),
        ):
            return await self.run_multipart(prompt, agent, session_id, files, images)

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
                    if not file.file_data.startswith(("http://", "https://", "data:", "s3://")) and not file.mime_type:
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
                    if not image.image_data.startswith(("http://", "https://", "data:", "s3://")) and not image.mime_type:
                        raise ValueError("mime_type is missing for image input, either in the base64 or explicitly")
                    requests.append(
                        AgentRequestImage(
                            image_data=image.image_data,
                            name=image.name,
                            mime_type=image.mime_type if image.mime_type else None,
                        )
                    )

            # Pack additional properties into AgentRequestAny
            known_fields = {"prompt", "agent", "session_id", "files", "images"}
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
                    str(result) if isinstance(result, (AgentReplyText, AgentReplyImage)) else "Non textual result received"
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
                    "session_id": (service.get_response_session_id(req.session_id) if service is not None else req.session_id),
                },
            )
        except Exception as e:
            self._log.error(f"POST /run error: {e}\n{traceback.format_exc()}")
            raise HTTPException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail={
                    "error": str(e),
                    "session_id": service.get_response_session_id(None) if service is not None else req.session_id,
                },
            )

    async def run_multipart(
        self,
        prompt: str,
        agent: Optional[str] = None,
        session_id: Optional[str] = None,
        files: Optional[List[UploadFile]] = None,
        images: Optional[List[UploadFile]] = None,
    ):
        """
        Async method to run the agent with multipart file uploads.
        :param prompt: The text prompt for the agent.
        :param agent: Optional agent name.
        :param session_id: Optional session ID.
        :param files: Optional list of uploaded files (documents, PDFs, CSVs, etc.).
        :param images: Optional list of uploaded images (JPEG, PNG, etc.).
        """
        requests = []
        requests.append(AgentRequestText(text=prompt))
        service = None

        try:
            # Process file uploads
            if files:
                for file in files:
                    self._log.debug(f"Processing uploaded file: {file.filename}")
                    # Read file content
                    content = await file.read()

                    # Validate file size
                    file_size = len(content)
                    if file_size > self._max_file_size:
                        raise ValueError(
                            f"File {file.filename} exceeds maximum size of {self._max_file_size / (1024 * 1024):.2f} MB "
                            f"(size: {file_size / (1024 * 1024):.2f} MB)"
                        )

                    # Encode to base64
                    file_data_base64 = base64.b64encode(content).decode("utf-8")

                    # Get mime type from the upload
                    mime_type = file.content_type

                    self._log.debug(f"Adding file attachment: {file.filename} (type: {mime_type})")
                    requests.append(
                        AgentRequestFile(
                            file_data=file_data_base64,
                            name=file.filename or "unknown",
                            mime_type=mime_type,
                        )
                    )

            # Process image uploads
            if images:
                for image in images:
                    self._log.debug(f"Processing uploaded image: {image.filename}")
                    # Read image content
                    content = await image.read()

                    # Validate image size
                    image_size = len(content)
                    if image_size > self._max_file_size:
                        raise ValueError(
                            f"Image {image.filename} exceeds maximum size of {self._max_file_size / (1024 * 1024):.2f} MB "
                            f"(size: {image_size / (1024 * 1024):.2f} MB)"
                        )

                    # Encode to base64
                    image_data_base64 = base64.b64encode(content).decode("utf-8")

                    # Get mime type from the upload
                    mime_type = image.content_type

                    # Validate it's an image mime type
                    if mime_type and not mime_type.startswith("image/"):
                        raise ValueError(f"Invalid image type: {mime_type} for file {image.filename}")

                    self._log.debug(f"Adding image: {image.filename} (type: {mime_type})")
                    requests.append(
                        AgentRequestImage(
                            image_data=image_data_base64,
                            name=image.filename or "unknown",
                            mime_type=mime_type,
                        )
                    )

            service = AgentService()
            service.select(session_id, agent)

            if not service.agent:
                raise ValueError("No agent available")

            result = await service.run_multi(requests=requests)
            self._log.debug(f"Result: {result}")

            return {
                "result": (str(result) if isinstance(result, (AgentReplyText, AgentReplyImage)) else "Non textual result received"),
                "session_id": service.get_response_session_id(session_id),
            }

        except HTTPException:
            raise
        except ValueError as e:
            self._log.error(f"POST /run-multipart error: {e}\n{traceback.format_exc()}")
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail={
                    "error": str(e),
                    "session_id": service.get_response_session_id(session_id) if service is not None else session_id,
                },
            )
        except Exception as e:
            self._log.error(f"POST /run-multipart error: {e}\n{traceback.format_exc()}")
            raise HTTPException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail={
                    "error": str(e),
                    "session_id": service.get_response_session_id(None) if service is not None else session_id,
                },
            )
