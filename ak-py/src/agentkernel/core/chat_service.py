import asyncio
import base64
import logging
from typing import Any, Dict, List, Optional, Union

from .config import AKConfig
from .model import (
    AgentReplyImage,
    AgentReplyText,
    AgentRequestAny,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
    BaseRunRequest,
    BaseChatRequest,
)
from .service import AgentService


class RequestBuilder:
    """Constructs AgentRequest object lists from various input sources."""

    _log = logging.getLogger("ak.chatservice.requestbuilder")
    _max_file_size = AKConfig.get().api.max_file_size  # 10 MB

    @staticmethod
    def from_base_request_sync(req: BaseRunRequest) -> List[Any]:
        """Build agent request list from BaseRunRequest synchronously.

        :param req: Base run request containing prompt, images, files, and additional context
        :return: List of AgentRequest objects for processing
        """
        requests = [AgentRequestText(text=req.prompt)]
        RequestBuilder._add_images(requests, req.images)
        RequestBuilder._add_files(requests, req.files)
        RequestBuilder._attach_additional_context(req, requests)
        return requests

    @staticmethod
    async def from_base_request_async(req: BaseChatRequest) -> List[Any]:
        """Build agent request list from a BaseChatRequest asynchronously.

        :param req: Base chat request (may be a BaseRunRequest with FileData/ImageData
                    or a multipart/upload-style request defined elsewhere)
        :return: List of AgentRequest objects for processing
        """
        requests = [AgentRequestText(text=req.prompt)]

        # If this is a BaseRunRequest, it contains FileData/ImageData objects
        # (base64 or URLs) — handle them synchronously. Otherwise, assume
        # multipart/upload-style objects and attempt to process them
        # via the async multipart handlers.
        if isinstance(req, BaseRunRequest):
            RequestBuilder._add_images(requests, req.images)
            RequestBuilder._add_files(requests, req.files)
            RequestBuilder._attach_additional_context(req, requests)
        else:
            # For other subclasses (e.g., upload objects) try async multipart
            await RequestBuilder._add_multipart_files(requests, getattr(req, "files", None))
            await RequestBuilder._add_multipart_images(requests, getattr(req, "images", None))

        return requests

    @staticmethod
    def _add_images(requests: List[Any], images):
        """Add image requests to the request list.

        :param requests: List to append image requests to
        :param images: List of image objects with image_data, name, and mime_type
        :return: None
        """
        if not images:
            return
        for image in images:
            RequestBuilder._log.debug(f"Adding image: {image.name}")
            if not image.image_data.startswith(("http://", "https://", "data:", "s3://")) and not image.mime_type:
                raise ValueError("mime_type is missing for image input, either in the base64 or explicitly")
            requests.append(
                AgentRequestImage(
                    image_data=image.image_data,
                    name=image.name,
                    mime_type=image.mime_type,
                )
            )

    @staticmethod
    def _add_files(requests: List[Any], files):
        """Add file requests to the request list.

        :param requests: List to append file requests to
        :param files: List of file objects with file_data, name, and mime_type
        :return: None
        """
        if not files:
            return
        for file in files:
            RequestBuilder._log.debug(f"Adding file attachment: {file.name}")
            if not file.file_data.startswith(("http://", "https://", "data:", "s3://")) and not file.mime_type:
                raise ValueError("mime_type is missing for file input, either in the base64 or explicitly")
            requests.append(
                AgentRequestFile(
                    file_data=file.file_data,
                    name=file.name,
                    mime_type=file.mime_type,
                )
            )

    @staticmethod
    def _attach_additional_context(req: BaseRunRequest, requests: List[Any]):
        """Attach additional context fields from request as AgentRequestAny objects.

        :param req: Base run request containing additional context fields
        :param requests: List to append context requests to
        :return: None
        """
        known_fields = {"request_id", "user_id", "prompt", "agent", "session_id", "images", "files"}
        for key, value in req.model_dump().items():
            if key in known_fields:
                continue
            RequestBuilder._log.info(f"Adding additional context: {key}={value}")
            requests.append(AgentRequestAny(name=key, content=value))

    @staticmethod
    async def _add_multipart_files(requests: List[Any], files: Optional[List[Any]]):
        """Process and add multipart uploaded files to request list.

        :param requests: List to append file requests to
        :param files: Optional list of uploaded file objects from multipart form
        :return: None
        """
        if not files:
            return
        for file in files:
            RequestBuilder._log.debug(f"Processing uploaded file: {file.filename}")
            content = await file.read()
            if len(content) > RequestBuilder._max_file_size:
                raise ValueError(f"File {file.filename} exceeds maximum size ({len(content) / (1024 * 1024):.2f} MB)")
            requests.append(
                AgentRequestFile(
                    file_data=base64.b64encode(content).decode("utf-8"),
                    name=file.filename or "unknown",
                    mime_type=file.content_type,
                )
            )

    @staticmethod
    async def _add_multipart_images(requests: List[Any], images: Optional[List[Any]]):
        """Process and add multipart uploaded images to request list.

        :param requests: List to append image requests to
        :param images: Optional list of uploaded image objects from multipart form
        :return: None
        """
        if not images:
            return
        for image in images:
            RequestBuilder._log.debug(f"Processing uploaded image: {image.filename}")
            content = await image.read()
            if len(content) > RequestBuilder._max_file_size:
                raise ValueError(f"Image {image.filename} exceeds maximum size ({len(content) / (1024 * 1024):.2f} MB)")
            if image.content_type and not image.content_type.startswith("image/"):
                raise ValueError(f"Invalid image type: {image.content_type}")
            requests.append(
                AgentRequestImage(
                    image_data=base64.b64encode(content).decode("utf-8"),
                    name=image.filename or "unknown",
                    mime_type=image.content_type,
                )
            )


class AgentHandler:
    """Manages AgentService lifecycle: selection, validation, and execution."""

    _log = logging.getLogger("ak.chatservice.agenthandler")

    def __init__(self):
        """Initialize AgentHandler with no active service.

        :return: None
        """
        self.service: Optional[AgentService] = None

    def initialize(self, session_id: str, agent: Optional[str]):
        """Initialize AgentService with session and agent selection.

        :param session_id: Session identifier for the agent
        :param agent: Optional agent name/identifier to select
        :return: None
        :raises ValueError: If no agent is available after selection
        """
        self.service = AgentService()
        self.service.select(session_id, agent)
        if not self.service.agent:
            raise ValueError("No agent available")

    def run_sync(self, requests: List[Any]) -> Any:
        """Run agent requests synchronously.

        :param requests: List of AgentRequest objects to process
        :return: Agent execution result
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                asyncio.set_event_loop(asyncio.new_event_loop())
                return asyncio.run(self.service.run_multi(requests=requests))
            else:
                return loop.run_until_complete(self.service.run_multi(requests=requests))
        except RuntimeError:
            return asyncio.run(self.service.run_multi(requests=requests))

    async def run_async(self, requests: List[Any]) -> Any:
        """Run agent requests asynchronously.

        :param requests: List of AgentRequest objects to process
        :return: Agent execution result
        """
        return await self.service.run_multi(requests=requests)

    def get_response_session_id(self, session_id: Optional[str]) -> Optional[str]:
        """Get the session ID for the response.

        :param session_id: Original session ID from request
        :return: Response session ID from service or original if service unavailable
        """
        return self.service.get_response_session_id(session_id) if self.service else session_id


class ResponseBuilder:
    """Formats agent results and errors into response dicts."""

    @staticmethod
    def success(status_code: int, result: Any, session_id: str, rest_api_mode: bool):
        """Build success response from agent result.

        :param status_code: HTTP status code for success
        :param result: Agent execution result
        :param session_id: Session identifier for the response
        :param rest_api_mode: If True, return dict only; if False, return tuple
        :return: Response dict or (status_code, response_dict) tuple
        """
        response_dict = {
            "result": str(result) if isinstance(result, (AgentReplyText, AgentReplyImage)) else "Non textual result received",
            "session_id": session_id,
        }
        return response_dict if rest_api_mode else (status_code, response_dict)

    @staticmethod
    def error(status_code: int, error: Exception, session_id: Optional[str], rest_api_mode: bool):
        """Build error response from exception.

        :param status_code: HTTP status code for error
        :param error: Exception that occurred
        :param session_id: Session identifier for the response
        :param rest_api_mode: If True, raise HTTPException; if False, return tuple
        :return: (status_code, response_dict) tuple or raises HTTPException
        """
        response_dict = {
            "error": str(error),
            "session_id": session_id,
        }
        if rest_api_mode:
            from fastapi import HTTPException

            raise HTTPException(status_code=status_code, detail=response_dict)
        return (status_code, response_dict)


class ChatService:
    def __init__(self, rest_api_mode: bool = False):
        """Initialize ChatService.

        :param rest_api_mode: If True, use FastAPI error handling; if False, use tuple responses
        :return: None
        """
        self._log = logging.getLogger("ak.chatservice")
        self.rest_api_mode = rest_api_mode

    def process_chat_request(self, req: BaseRunRequest) -> Union[tuple[int, Dict[str, Any]], Dict[str, Any]]:
        """Process a chat request synchronously.

        :param req: Base run request with prompt, session_id, agent, and attachments
        :return: When rest_api_mode=False: tuple of (status_code, response_dict).
                 When rest_api_mode=True: response_dict only.
        """
        session_id = req.session_id
        handler = AgentHandler()
        try:
            self._validate(req)
            requests = RequestBuilder.from_base_request_sync(req)
            handler.initialize(session_id, req.agent)
            result = handler.run_sync(requests)
            return ResponseBuilder.success(200, result, handler.get_response_session_id(session_id), self.rest_api_mode)
        except ValueError as ve:
            self._log.error(f"ValueError processing request: {ve}")
            return ResponseBuilder.error(400, ve, handler.get_response_session_id(session_id), self.rest_api_mode)
        except Exception as e:
            self._log.error(f"Error processing request: {e}")
            return ResponseBuilder.error(500, e, handler.get_response_session_id(None), self.rest_api_mode)

    async def process_async_chat_request(self, req: BaseChatRequest) -> Union[tuple[int, Dict[str, Any]], Dict[str, Any]]:
        """Process a chat request asynchronously.

        :param req: Base chat request (could be a BaseRunRequest or another subclass
                    that represents multipart/upload requests).
        :return: When rest_api_mode=False: tuple of (status_code, response_dict).
                 When rest_api_mode=True: response_dict only.
        """
        session_id = req.session_id
        handler = AgentHandler()
        try:
            if not session_id:
                raise ValueError("No session_id is provided in the request")
            if not req.prompt:
                raise ValueError("No prompt provided in the request")
            requests = await RequestBuilder.from_base_request_async(req)
            handler.initialize(session_id, req.agent)
            result = await handler.run_async(requests)
            return ResponseBuilder.success(200, result, handler.get_response_session_id(session_id), self.rest_api_mode)
        except ValueError as ve:
            self._log.error(f"ValueError processing request: {ve}")
            return ResponseBuilder.error(400, ve, handler.get_response_session_id(session_id), self.rest_api_mode)
        except Exception as e:
            self._log.error(f"Error processing request: {e}")
            return ResponseBuilder.error(500, e, handler.get_response_session_id(session_id), self.rest_api_mode)

    @staticmethod
    def _validate(req: BaseRunRequest):
        """Validate that required fields are present in the request.

        :param req: Base run request to validate
        :return: None
        :raises ValueError: If session_id or prompt is missing
        """
        if req.session_id is None:
            raise ValueError("No session_id is provided in the request")
        if not req.prompt:
            raise ValueError("No prompt provided in the request")
