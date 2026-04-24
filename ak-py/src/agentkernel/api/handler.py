import logging
from abc import ABC, abstractmethod
from typing import List, Optional
from fastapi import APIRouter, File, Form, UploadFile
from agentkernel.core.model import BaseRunRequest
from ..core import Config
from ..core.runtime import Runtime
from ..core.chat_service import ChatService


class RESTRequestHandler(ABC):
    @abstractmethod
    def get_router(self) -> APIRouter:
        """
        Returns the APIRouter instance which has configured routes
        E.g.:
        - GET /api/v1/agents: List available agents

        router = APIRouter()

        @router.get("/api/v1/agents")
        def list_agents():
            from ..core.runtime import Runtime
            return {"agents": list(Runtime.current().agents().keys())}

        """
        pass


class AgentRESTRequestHandler(RESTRequestHandler):
    """
    API routers that expose endpoints to interact with Agent Kernel.
    Endpoints:
    - GET /api/v1/agents: List available agents
    - POST /api/v1/chat: Run an agent with a prompt
      Payload JSON: { "prompt": str, "agent": str | null, "session_id": str | null }
    """

    def __init__(self):
        self._log = logging.getLogger("ak.api.agent")
        self._max_file_size = Config.get().api.max_file_size
        self.chat_service = ChatService(rest_api_mode=True)

    def get_router(self) -> APIRouter:
        """
        Returns the APIRouter instance.
        """

        router = APIRouter()

        @router.get("/api/v1/agents")
        def list_agents():
            return {"agents": list(Runtime.current().agents().keys())}

        @router.post("/api/v1/chat")
        async def run(body: BaseRunRequest):
            return await self.chat_service.process_chat_request_async(req=body)

        @router.post("/api/v1/chat-multipart")
        async def run_multipart(
            prompt: str = Form(...),
            agent: Optional[str] = Form(None),
            session_id: Optional[str] = Form(None),
            files: Optional[List[UploadFile]] = File(None),
            images: Optional[List[UploadFile]] = File(None),
        ):
            return await self.chat_service.process_multipart_request_async(
                prompt=prompt,
                agent=agent,
                session_id=session_id,
                files=files,
                images=images,
            )

        return router

    # async def run_multipart(
    #     self,
    #     prompt: str,
    #     agent: Optional[str] = None,
    #     session_id: Optional[str] = None,
    #     files: Optional[List[UploadFile]] = None,
    #     images: Optional[List[UploadFile]] = None,
    # ):
    #     """
    #     Async method to run the agent with multipart file uploads.
    #     :param prompt: The text prompt for the agent.
    #     :param agent: Optional agent name.
    #     :param session_id: Optional session ID.
    #     :param files: Optional list of uploaded files (documents, PDFs, CSVs, etc.).
    #     :param images: Optional list of uploaded images (JPEG, PNG, etc.).
    #     """
    #     requests = []
    #     requests.append(AgentRequestText(text=prompt))
    #     service = None

    #     try:
    #         # Process file uploads
    #         if files:
    #             for file in files:
    #                 self._log.debug(f"Processing uploaded file: {file.filename}")
    #                 # Read file content
    #                 content = await file.read()

    #                 # Validate file size
    #                 file_size = len(content)
    #                 if file_size > self._max_file_size:
    #                     raise ValueError(
    #                         f"File {file.filename} exceeds maximum size of {self._max_file_size / (1024 * 1024):.2f} MB "
    #                         f"(size: {file_size / (1024 * 1024):.2f} MB)"
    #                     )

    #                 # Encode to base64
    #                 file_data_base64 = base64.b64encode(content).decode("utf-8")

    #                 # Get mime type from the upload
    #                 mime_type = file.content_type

    #                 self._log.debug(f"Adding file attachment: {file.filename} (type: {mime_type})")
    #                 requests.append(
    #                     AgentRequestFile(
    #                         file_data=file_data_base64,
    #                         name=file.filename or "unknown",
    #                         mime_type=mime_type,
    #                     )
    #                 )

    #         # Process image uploads
    #         if images:
    #             for image in images:
    #                 self._log.debug(f"Processing uploaded image: {image.filename}")
    #                 # Read image content
    #                 content = await image.read()

    #                 # Validate image size
    #                 image_size = len(content)
    #                 if image_size > self._max_file_size:
    #                     raise ValueError(
    #                         f"Image {image.filename} exceeds maximum size of {self._max_file_size / (1024 * 1024):.2f} MB "
    #                         f"(size: {image_size / (1024 * 1024):.2f} MB)"
    #                     )

    #                 # Encode to base64
    #                 image_data_base64 = base64.b64encode(content).decode("utf-8")

    #                 # Get mime type from the upload
    #                 mime_type = image.content_type

    #                 # Validate it's an image mime type
    #                 if mime_type and not mime_type.startswith("image/"):
    #                     raise ValueError(f"Invalid image type: {mime_type} for file {image.filename}")

    #                 self._log.debug(f"Adding image: {image.filename} (type: {mime_type})")
    #                 requests.append(
    #                     AgentRequestImage(
    #                         image_data=image_data_base64,
    #                         name=image.filename or "unknown",
    #                         mime_type=mime_type,
    #                     )
    #                 )

    #         service = AgentService()
    #         service.select(session_id, agent)

    #         if not service.agent:
    #             raise ValueError("No agent available")

    #         result = await service.run_multi(requests=requests)
    #         self._log.debug(f"Result: {result}")

    #         return {
    #             "result": (str(result) if isinstance(result, (AgentReplyText, AgentReplyImage)) else "Non textual result received"),
    #             "session_id": service.get_response_session_id(session_id),
    #         }

    #     except HTTPException:
    #         raise
    #     except ValueError as e:
    #         self._log.error(f"POST /api/v1/chat-multipart error: {e}\n{traceback.format_exc()}")
    #         raise HTTPException(
    #             status_code=HTTPStatus.BAD_REQUEST,
    #             detail={
    #                 "error": str(e),
    #                 "session_id": service.get_response_session_id(session_id) if service is not None else session_id,
    #             },
    #         )
    #     except Exception as e:
    #         self._log.error(f"POST /api/v1/chat-multipart error: {e}\n{traceback.format_exc()}")
    #         raise HTTPException(
    #             status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
    #             detail={
    #                 "error": str(e),
    #                 "session_id": service.get_response_session_id(None) if service is not None else session_id,
    #             },
    #         )
