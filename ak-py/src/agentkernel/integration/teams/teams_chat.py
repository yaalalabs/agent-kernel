import asyncio
import base64
import logging
import mimetypes
import re
import traceback
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

import httpx
import msal
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity, ActivityTypes, Attachment, ConversationReference
from botframework.connector.auth import MicrosoftAppCredentials
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from ...api import RESTRequestHandler
from ...core import ChatService, Config
from ...core.model import (
    AgentReply,
    AgentReplyAny,
    AgentReplyImage,
    AgentReplyText,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
    BaseChatRequest,
)

MAX_MESSAGE_LENGTH = 8000
FILE_DOWNLOAD_INFO = "application/vnd.microsoft.teams.file.download.info"
CONNECTOR_HOST_SUFFIXES = ("botframework.com", "trafficmanager.net", "skype.com", "skype.net")

GRAPH_HOST = "graph.microsoft.com"
PRE_AUTH_PARAMS = ("tempauth=", "access_token=", "authkey=")
AT_TAG_PATTERN = re.compile(r"<at\b[^>]*>(.*?)</at>", re.IGNORECASE | re.DOTALL)


class _AttachmentTooLarge(Exception):
    """Raised while streaming when an attachment exceeds api.max_file_size."""

    def __init__(self, size: int):
        super().__init__(f"attachment exceeds the maximum size ({size} bytes)")
        self.size = size


class AgentTeamsRequestHandler(RESTRequestHandler):
    """
    API routers that expose endpoints to interact with Microsoft Teams using Agent Kernel.

    This handler uses Azure Bot Framework to receive messages and send responses.
    Supports text, images, and files like WhatsApp/Messenger/Slack integrations.

    The agent runs outside the webhook turn, via a proactive `continue_conversation` follow
    up, so a long agent run cannot exceed the Bot Framework delivery timeout and make Azure
    redeliver the same activity.

    Endpoints:
    - GET /health: Health check
    - POST /teams/messages: Handle incoming Teams messages via Bot Framework
    """

    def __init__(self):
        self._log = logging.getLogger("ak.api.teams")
        self._teams_agent = Config.get().teams.agent if Config.get().teams.agent != "" else None
        self._teams_agent_acknowledgement = Config.get().teams.agent_acknowledgement if Config.get().teams.agent_acknowledgement != "" else None
        self._app_id = Config.get().teams.app_id
        self._app_password = Config.get().teams.app_password
        self._tenant_id = Config.get().teams.tenant_id
        self._max_file_size = Config.get().api.max_file_size
        self._chat_service = ChatService()

        if not self._app_id or not self._app_password:
            self._log.error("Teams configuration is incomplete. Please set app_id and app_password.")
            raise ValueError("Incomplete Teams configuration.")

        if self._tenant_id:
            self._log.info(f"Using Teams App ID: {self._app_id} with Tenant ID: {self._tenant_id}")
        else:
            self._log.info(
                f"Using Teams App ID: {self._app_id} (Multi Tenant). The tenant is taken from each incoming activity; "
                "set teams.tenant_id to pin it."
            )

        settings = BotFrameworkAdapterSettings(self._app_id, self._app_password, channel_auth_tenant=self._tenant_id or None)
        self._adapter = BotFrameworkAdapter(settings)
        self._adapter.on_turn_error = self._on_turn_error

        self._msal_apps: Dict[str, msal.ConfidentialClientApplication] = {}
        self._bot_credentials: Optional[MicrosoftAppCredentials] = None
        self._background_tasks: Set[asyncio.Task] = set()

    def get_router(self) -> APIRouter:
        """
        Returns the APIRouter instance.
        """
        router = APIRouter()

        @router.get("/health")
        def health():
            return {"status": "ok"}

        @router.post("/teams/messages")
        async def handle_message(request: Request):
            """
            Handle incoming Teams messages via Bot Framework.
            """
            auth_header = request.headers.get("Authorization", "")
            self._log.debug(f"Received Teams activity, auth header present: {bool(auth_header)}")

            try:
                body = await request.json()
            except Exception as e:
                self._log.warning(f"Teams activity body is not valid JSON: {e}")
                raise HTTPException(status_code=400, detail="Invalid request body")

            try:
                invoke_response = await self._adapter.process_activity({"body": body}, auth_header, self._on_turn)
            except PermissionError as pe:
                self._log.warning(f"Rejected unauthenticated Teams activity: {pe}")
                raise HTTPException(status_code=401, detail="Unauthorized")
            except Exception as e:
                self._log.error(f"Error processing Teams message: {str(e)}\n{traceback.format_exc()}")
                raise HTTPException(status_code=500, detail="Internal server error")

            if invoke_response is not None:
                return JSONResponse(status_code=invoke_response.status, content=invoke_response.body)
            return Response(status_code=200)

        return router

    async def _on_turn_error(self, turn_context: TurnContext, error: Exception):
        """Adapter-level fallback so a failure anywhere in the pipeline still reaches the user."""
        self._log.error(f"Unhandled error in Teams turn: {error}\n{traceback.format_exc()}")
        try:
            await turn_context.send_activity("Sorry, an error occurred while processing your request.")
        except Exception as e:
            self._log.error(f"Could not deliver the Teams error message: {e}")

    async def _on_turn(self, turn_context: TurnContext):
        """
        Accept an incoming Teams activity and hand the agent run off to a background turn.
        """
        activity: Activity = turn_context.activity

        # Only handle message activities
        if activity.type != ActivityTypes.message:
            self._log.debug(f"Ignoring Teams activity of type '{activity.type}'")
            return

        text = self._strip_mentions(activity)
        attachments = [a for a in (activity.attachments or []) if (a.content_type or "") != "text/html"]
        user_name = (activity.from_property.name if activity.from_property else None) or "User"

        # Skip empty messages
        if not text and not attachments:
            return

        self._log.info(f"Received Teams message from {user_name}: {text[:100]}")
        rejected = [self._attachment_name(a) for a in attachments if self._declared_mime(a).startswith(("audio/", "video/"))]
        if rejected:
            await self._send_text(
                turn_context,
                "I can only process text messages, images, and document files. "
                f"The following audio/video files were rejected: {', '.join(rejected)}",
            )
            return

        if self._teams_agent_acknowledgement:
            await self._send_text(turn_context, f"Hi {user_name}, {self._teams_agent_acknowledgement}")

        reference = TurnContext.get_conversation_reference(activity)
        task = asyncio.create_task(self._run_agent_turn(reference, activity, text, attachments, user_name))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _run_agent_turn(
        self,
        reference: ConversationReference,
        activity: Activity,
        text: str,
        attachments: List[Attachment],
        user_name: str,
    ):
        """
        Continue the conversation proactively so the agent run is not bounded by the
        Bot Framework delivery timeout on the inbound webhook.
        """

        async def _callback(turn_context: TurnContext):
            await self._handle_teams_message(turn_context, activity, text, attachments, user_name)

        try:
            await self._adapter.continue_conversation(reference, _callback, self._app_id)
        except Exception as e:
            self._log.error(f"Failed to continue the Teams conversation: {e}\n{traceback.format_exc()}")

    async def _handle_teams_message(
        self,
        turn_context: TurnContext,
        activity: Activity,
        text: str,
        attachments: List[Attachment],
        user_name: str,
    ):
        """
        Download attachments, run the agent, and send the reply.
        """
        conversation_id = activity.conversation.id if activity.conversation else None

        try:
            requests = []
            if text:
                requests.append(AgentRequestText(prompt=text))

            if attachments:
                rejected, oversized, failed, unauthorised = await self._process_attachments(attachments, requests, self._resolve_tenant(activity))
                if rejected:
                    await self._send_text(
                        turn_context,
                        "I can only process text messages, images, and document files. "
                        f"The following audio/video files were rejected: {', '.join(rejected)}",
                    )
                    return
                if oversized:
                    await self._send_text(
                        turn_context,
                        f"Sorry {user_name}, the following files exceed the maximum size of "
                        f"{self._max_file_size / (1024 * 1024):.2f} MB: {', '.join(oversized)}",
                    )
                    return
                if unauthorised:
                    await self._send_text(
                        turn_context,
                        f"Sorry {user_name}, I am not allowed to download the following files: {', '.join(unauthorised)}. "
                        "File downloads are not configured correctly — please contact your administrator.",
                    )
                    return
                if failed:
                    await self._send_text(
                        turn_context,
                        f"Sorry {user_name}, I could not download the following files: {', '.join(failed)}. Please try again.",
                    )
                    return

            if not requests:
                await self._send_text(turn_context, "Please provide a message or attachment.")
                return

            req = BaseChatRequest(
                prompt=text,
                agent=self._teams_agent,
                session_id=conversation_id,
                user_id=activity.from_property.id if activity.from_property else None,
                group_id=self._resolve_group(activity),
            )
            try:
                reply, _ = await self._chat_service.execute(req, requests=requests)
            except ValueError as ve:
                self._log.warning(f"Agent execution rejected: {ve} (session_id: {conversation_id})")
                await self._send_text(turn_context, "No agent available to handle your request.")
                return

            await self._send_reply(turn_context, reply, user_name)

        except Exception as e:
            self._log.error(f"Error processing agent message: {str(e)}\n{traceback.format_exc()}")
            await self._send_text(turn_context, f"Sorry {user_name}, an error occurred while processing your request.")

    def _strip_mentions(self, activity: Activity) -> str:
        """
        Remove the bot's own @mention from the message text.

        Mentions of other people keep their display name so the agent still sees who was
        referred to, and text that merely looks like a handle (an email address, a Python
        decorator) is left untouched.
        """
        text = activity.text or ""
        if not text:
            return ""

        bot_id = activity.recipient.id if activity.recipient else None
        bot_names = set()
        if activity.recipient and activity.recipient.name:
            bot_names.add(activity.recipient.name)

        for entity in activity.entities or []:
            if (entity.type or "").lower() != "mention":
                continue
            properties = entity.additional_properties or {}
            mentioned = properties.get("mentioned") or {}
            if bot_id and mentioned.get("id") != bot_id:
                continue
            # `text` carries the literal "<at ...>Name</at>" fragment as it appears in the message
            raw = properties.get("text")
            if raw:
                text = text.replace(raw, " ")
            elif mentioned.get("name"):
                bot_names.add(mentioned["name"])

        def _replace(match: "re.Match") -> str:
            label = match.group(1)
            return " " if label.strip() in bot_names else label

        text = AT_TAG_PATTERN.sub(_replace, text)
        return re.sub(r"(?<=\S)[ \t]{2,}", " ", text).strip()

    def _resolve_tenant(self, activity: Activity) -> Optional[str]:
        """
        Resolve the Entra ID tenant that owns this conversation.

        The adapter copies the Teams tenant from channelData onto conversation.tenant_id; the
        configured tenant_id is the fallback. A tenant is required because the app-only token
        grant is illegal against the /common authority.
        """
        conversation = activity.conversation
        if conversation is not None and getattr(conversation, "tenant_id", None):
            return conversation.tenant_id
        tenant = ((activity.channel_data or {}).get("tenant") or {}).get("id")
        return tenant or self._tenant_id or None

    @staticmethod
    def _resolve_group(activity: Activity) -> Optional[str]:
        """Return the Teams channel or team the message came from, if any."""
        channel_data = activity.channel_data or {}
        channel = channel_data.get("channel") or {}
        team = channel_data.get("team") or {}
        return channel.get("id") or team.get("id")

    @staticmethod
    def _attachment_name(attachment: Attachment) -> str:
        """Best available file name for an attachment, including inline images that carry none."""
        if attachment.name:
            return attachment.name
        content_type = attachment.content_type or ""
        if content_type.startswith("image/"):
            extension = mimetypes.guess_extension(content_type) or ".png"
            return f"image{extension}"
        return "file"

    @staticmethod
    def _declared_mime(attachment: Attachment) -> str:
        """
        Best guess at an attachment's real media type from the activity alone.

        Uploaded files arrive wrapped as FILE_DOWNLOAD_INFO and inline images as the
        placeholder "image/*", so neither content type identifies the payload on its own.
        """
        content_type = attachment.content_type or ""
        if content_type and content_type != FILE_DOWNLOAD_INFO and not content_type.endswith("/*"):
            return content_type

        name = attachment.name or ""
        content = attachment.content if isinstance(attachment.content, dict) else {}
        file_type = content.get("fileType") or ""
        if not name and file_type:
            name = f"file.{file_type}"
        guessed, _ = mimetypes.guess_type(name)
        return guessed or content_type

    async def _process_attachments(
        self,
        attachments: List[Attachment],
        requests: List,
        tenant_id: Optional[str],
    ) -> Tuple[List[str], List[str], List[str], List[str]]:
        """
        Process Teams attachments (images and files) and append them to `requests`.

        :return: (rejected, oversized, failed, unauthorised) file name lists. Each is reported
                 to the user with its own message, since they need different remedies.
        """
        rejected: List[str] = []
        oversized: List[str] = []
        failed: List[str] = []
        unauthorised: List[str] = []

        for attachment in attachments:
            name = self._attachment_name(attachment)
            content_type = self._declared_mime(attachment)
            content_url = attachment.content_url

            # An uploaded file carries its real, often pre-authenticated, URL in `content`.
            if attachment.content_type == FILE_DOWNLOAD_INFO and isinstance(attachment.content, dict):
                content_url = attachment.content.get("downloadUrl") or content_url

            if not content_url:
                self._log.warning(f"Attachment '{name}' has no content URL. Type: '{attachment.content_type}'.")
                failed.append(name)
                continue

            if content_type.startswith(("audio/", "video/")):
                rejected.append(name)
                continue

            try:
                headers = await self._download_headers(content_url, tenant_id)
            except PermissionError as pe:
                self._log.error(f"Cannot authorize the download of '{name}': {pe}")
                unauthorised.append(name)
                continue

            try:
                file_data, resolved_type = await self._download(content_url, headers)
            except _AttachmentTooLarge as too_large:
                oversized.append(f"{name} ({too_large.size / (1024 * 1024):.2f} MB)")
                continue
            except Exception as e:
                self._log.warning(f"Download failed for {name}: {e}")
                failed.append(name)
                continue

            if file_data is None:
                failed.append(name)
                continue

            if resolved_type and resolved_type != "application/octet-stream":
                content_type = resolved_type

            if content_type.startswith(("audio/", "video/")):
                rejected.append(name)
                continue

            encoded = base64.b64encode(file_data).decode("utf-8")
            if content_type.startswith("image/"):
                requests.append(AgentRequestImage(image_data=encoded, name=name, mime_type=content_type))
                self._log.info(f"Image {name} added to request")
            else:
                requests.append(AgentRequestFile(file_data=encoded, name=name, mime_type=content_type))
                self._log.info(f"File {name} added to request")

        return rejected, oversized, failed, unauthorised

    async def _download_headers(self, content_url: str, tenant_id: Optional[str]) -> Dict[str, str]:
        """
        Build the Authorization header for an attachment URL.

        A bearer is only ever sent to a host whose audience it was minted for; an
        unrecognised host is fetched without one rather than being handed a token.

        :raises PermissionError: when the host needs a token that cannot be obtained.
        """
        if any(param in content_url for param in PRE_AUTH_PARAMS):
            return {}

        host = (urlparse(content_url).hostname or "").lower()

        if any(host == suffix or host.endswith(f".{suffix}") for suffix in CONNECTOR_HOST_SUFFIXES):
            token = await self._bot_framework_token()
            if not token:
                raise PermissionError(f"could not obtain a Bot Framework token for {host}")
            return {"Authorization": f"Bearer {token}"}

        if host == GRAPH_HOST:
            scope = f"https://{GRAPH_HOST}/.default"
        elif host == "sharepoint.com" or host.endswith(".sharepoint.com"):
            scope = f"https://{host}/.default"
        else:
            self._log.debug(f"No known token audience for download host '{host}'; fetching without authorization")
            return {}

        if not tenant_id:
            raise PermissionError(
                f"{host} requires an app-only token but no tenant is known. Set teams.tenant_id "
                "(the client credentials grant is not valid against the /common authority)."
            )

        result = await asyncio.to_thread(self._acquire_token, tenant_id, scope)
        if "access_token" not in result:
            raise PermissionError(
                f"token request for {scope} in tenant {tenant_id} failed: " f"{result.get('error')} - {result.get('error_description')}"
            )
        return {"Authorization": f"Bearer {result['access_token']}"}

    def _acquire_token(self, tenant_id: str, scope: str) -> dict:
        """Acquire an app-only token, building and caching the tenant's MSAL client on first use."""
        app = self._msal_apps.get(tenant_id)
        if app is None:
            app = msal.ConfidentialClientApplication(
                self._app_id,
                authority=f"https://login.microsoftonline.com/{tenant_id}",
                client_credential=self._app_password,
            )
            self._msal_apps[tenant_id] = app
        return app.acquire_token_for_client(scopes=[scope])

    async def _bot_framework_token(self) -> Optional[str]:
        """Return the bot's own Bot Framework token, used for Bot Connector attachment URLs."""
        if self._bot_credentials is None:
            # channel_auth_tenant matters for a single-tenant app registration: without it the token is
            # minted against /botframework.com and the authority rejects it with AADSTS700016.
            self._bot_credentials = MicrosoftAppCredentials(self._app_id, self._app_password, channel_auth_tenant=self._tenant_id or None)
        try:
            return await asyncio.to_thread(self._bot_credentials.get_access_token)
        except Exception as e:
            self._log.error(f"Could not acquire a Bot Framework token: {e}")
            return None

    async def _download(self, content_url: str, headers: Dict[str, str]) -> Tuple[Optional[bytes], Optional[str]]:
        """
        Stream an attachment, aborting as soon as it exceeds api.max_file_size.

        :return: (content, response content type); content is None when the server refused.
        :raises _AttachmentTooLarge: when the attachment is larger than the configured limit.
        """
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", content_url, headers=headers, timeout=30.0) as response:
                if response.status_code != 200:
                    self._log.warning(f"Direct download failed with status {response.status_code}.")
                    return None, None

                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > self._max_file_size:
                    raise _AttachmentTooLarge(int(declared))

                buffer = bytearray()
                async for chunk in response.aiter_bytes():
                    buffer.extend(chunk)
                    if len(buffer) > self._max_file_size:
                        raise _AttachmentTooLarge(len(buffer))

                content_type = response.headers.get("content-type", "")
                return bytes(buffer), content_type.split(";")[0].strip() or None

    async def _send_reply(self, turn_context: TurnContext, reply: AgentReply, user_name: str):
        """Send agent reply to Teams."""
        try:
            # Standardize reply handling similar to Slack/WhatsApp
            reply_text = str(reply) if isinstance(reply, (AgentReplyText, AgentReplyImage, AgentReplyAny)) else "Non textual result received"
            if not reply_text.strip():
                reply_text = "The agent returned an empty response."

            for chunk in self._split_reply(reply_text):
                await turn_context.send_activity(chunk)

        except Exception as e:
            self._log.error(f"Error sending reply to Teams: {e}")
            await self._send_text(turn_context, "Error sending agent response.")

    @staticmethod
    def _split_reply(reply: str) -> List[str]:
        """Split a reply into chunks Teams will accept, since it drops oversized activities."""
        if len(reply) <= MAX_MESSAGE_LENGTH:
            return [reply]
        return [reply[i : i + MAX_MESSAGE_LENGTH] for i in range(0, len(reply), MAX_MESSAGE_LENGTH)]

    async def _send_text(self, turn_context: TurnContext, text: str):
        """Send a status message, logging rather than raising when Teams refuses it."""
        try:
            await turn_context.send_activity(text)
        except Exception as e:
            self._log.error(f"Could not send a message to Teams: {e}")
