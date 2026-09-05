"""Microsoft Teams inbound/outbound adapter pair (spec #524 §9).

Teams is the other platform whose SDK owns the HTTP response: ``BotFrameworkAdapter``
authenticates the activity and may return an invoke response, so ``verify`` stays the base
no-op and ``parse`` runs ``process_activity``.

The proactive ``continue_conversation`` that used to escape the Bot Framework delivery timeout
inside the webhook process is now simply how the outbound adapter delivers: the
``ConversationReference`` travels across the queue as one JSON attribute.
"""

import asyncio
import base64
import json
import logging
import mimetypes
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
import msal
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity, ActivityTypes, Attachment, ConversationReference
from botframework.connector.auth import MicrosoftAppCredentials
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from ...core.config import AKConfig
from ...core.model import AgentReply, AgentRequest, AgentRequestFile, AgentRequestImage, AgentRequestText
from ...core.multimodal.storage.offload import offload_attachments
from ..adapter.base import ATTACHMENTS_DISABLED_ERROR, SESSION_CACHE_ERROR, InboundAdapter, InboundParseResult, InboundRequest, OutboundAdapter

NAME = "teams"

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


class _TeamsCredentials:
    """Everything both halves need to talk to Azure: settings, adapter, and token acquisition."""

    _log = logging.getLogger("ak.integration.teams")

    def __init__(self):
        config = AKConfig.get().teams
        self._app_id = config.app_id
        self._app_password = config.app_password
        self._tenant_id = config.tenant_id
        if not self._app_id or not self._app_password:
            self._log.error("Teams configuration is incomplete. Please set app_id and app_password.")
            raise ValueError("Incomplete Teams configuration.")

        settings = BotFrameworkAdapterSettings(self._app_id, self._app_password, channel_auth_tenant=self._tenant_id or None)
        self._adapter = BotFrameworkAdapter(settings)
        self._msal_apps: Dict[str, msal.ConfidentialClientApplication] = {}
        self._bot_credentials: Optional[MicrosoftAppCredentials] = None

    @property
    def adapter(self) -> BotFrameworkAdapter:
        return self._adapter

    @property
    def app_id(self) -> str:
        return self._app_id

    def acquire_token(self, tenant_id: str, scope: str) -> dict:
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

    async def bot_framework_token(self) -> Optional[str]:
        """The bot's own Bot Framework token, used for Bot Connector attachment URLs."""
        if self._bot_credentials is None:
            # channel_auth_tenant matters for a single-tenant app registration: without it the token
            # is minted against /botframework.com and the authority rejects it with AADSTS700016.
            self._bot_credentials = MicrosoftAppCredentials(self._app_id, self._app_password, channel_auth_tenant=self._tenant_id or None)
        try:
            return await asyncio.to_thread(self._bot_credentials.get_access_token)
        except Exception as e:
            self._log.error(f"Could not acquire a Bot Framework token: {e}")
            return None

    def resolve_tenant(self, activity: Activity) -> Optional[str]:
        """Resolve the Entra ID tenant that owns this conversation.

        The adapter copies the Teams tenant from channelData onto conversation.tenant_id; the
        configured tenant_id is the fallback. A tenant is required because the app-only token
        grant is illegal against the /common authority.
        """
        conversation = activity.conversation
        if conversation is not None and getattr(conversation, "tenant_id", None):
            return conversation.tenant_id
        tenant = ((activity.channel_data or {}).get("tenant") or {}).get("id")
        return tenant or self._tenant_id or None


class TeamsInboundAdapter(InboundAdapter):
    """Teams activities -> normalized requests."""

    name = NAME
    webhook_path = "/teams/messages"

    _log = logging.getLogger("ak.integration.teams")

    def __init__(self):
        config = AKConfig.get()
        self._agent = config.teams.agent or None
        self._max_file_size = config.api.max_file_size
        self._credentials = _TeamsCredentials()
        self._credentials.adapter.on_turn_error = self._on_turn_error

        if config.teams.tenant_id:
            self._log.info(f"Using Teams App ID: {self._credentials.app_id} with Tenant ID: {config.teams.tenant_id}")
        else:
            self._log.info(
                f"Using Teams App ID: {self._credentials.app_id} (Multi Tenant). The tenant is taken from each incoming activity; "
                "set teams.tenant_id to pin it."
            )

    async def parse(self, raw: Request) -> InboundParseResult:
        """Run the Bot Framework's dispatch and normalize the message activity it delivers."""
        auth_header = raw.headers.get("Authorization", "")
        self._log.debug(f"Received Teams activity, auth header present: {bool(auth_header)}")
        try:
            body = await raw.json()
        except Exception as e:
            self._log.warning(f"Teams activity body is not valid JSON: {e}")
            raise HTTPException(status_code=400, detail="Invalid request body")

        parsed: List[InboundRequest] = []

        async def _on_turn(turn_context: TurnContext) -> None:
            request = await self._to_request(turn_context)
            if request is not None:
                parsed.append(request)

        try:
            invoke_response = await self._credentials.adapter.process_activity({"body": body}, auth_header, _on_turn)
        except PermissionError as pe:
            self._log.warning(f"Rejected unauthenticated Teams activity: {pe}")
            raise HTTPException(status_code=401, detail="Unauthorized")
        except HTTPException:
            raise
        except Exception as e:
            self._log.error(f"Error processing Teams message: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

        response = JSONResponse(status_code=invoke_response.status, content=invoke_response.body) if invoke_response is not None else None
        return InboundParseResult(requests=parsed, response=response)

    async def _to_request(self, turn_context: TurnContext) -> Optional[InboundRequest]:
        """Normalize one Teams activity, or None when it carries nothing to run."""
        activity: Activity = turn_context.activity
        if activity.type != ActivityTypes.message:
            self._log.debug(f"Ignoring Teams activity of type '{activity.type}'")
            return None

        text = self._strip_mentions(activity)
        attachments = [a for a in (activity.attachments or []) if (a.content_type or "") != "text/html"]
        user_name = (activity.from_property.name if activity.from_property else None) or "User"
        if not text and not attachments:
            return None

        self._log.info(f"Received Teams message from {user_name}: {text[:100]}")

        rejected = [self._attachment_name(a) for a in attachments if self._declared_mime(a).startswith(("audio/", "video/"))]
        if rejected:
            await self._send(
                turn_context,
                "I can only process text messages, images, and document files. "
                f"The following audio/video files were rejected: {', '.join(rejected)}",
            )
            return None

        requests: List[AgentRequest] = []
        if text:
            requests.append(AgentRequestText(prompt=text))

        if attachments:
            rejected, oversized, failed, unauthorised = await self._process_attachments(
                attachments, requests, self._credentials.resolve_tenant(activity)
            )
            if rejected:
                await self._send(
                    turn_context,
                    "I can only process text messages, images, and document files. "
                    f"The following audio/video files were rejected: {', '.join(rejected)}",
                )
                return None
            if oversized:
                await self._send(
                    turn_context,
                    f"Sorry {user_name}, the following files exceed the maximum size of "
                    f"{self._max_file_size / (1024 * 1024):.2f} MB: {', '.join(oversized)}",
                )
                return None
            if unauthorised:
                await self._send(
                    turn_context,
                    f"Sorry {user_name}, I am not allowed to download the following files: {', '.join(unauthorised)}. "
                    "File downloads are not configured correctly — please contact your administrator.",
                )
                return None
            if failed:
                await self._send(turn_context, f"Sorry {user_name}, I could not download the following files: {', '.join(failed)}. Please try again.")
                return None

        if not requests:
            await self._send(turn_context, "Please provide a message or attachment.")
            return None

        conversation_id = activity.conversation.id if activity.conversation else None
        requests, _ = offload_attachments(
            conversation_id,
            requests,
            attachments_disabled_error=ATTACHMENTS_DISABLED_ERROR,
            session_cache_error=SESSION_CACHE_ERROR,
        )

        # The reply is delivered proactively from another process, so the whole reference has to
        # travel: it is the only object in any adapter's reply context, hence the JSON encoding.
        reference = TurnContext.get_conversation_reference(activity)
        return InboundRequest(
            session_id=conversation_id,
            request_id=activity.id,
            requests=requests,
            prompt=text,
            agent=self._agent,
            user_id=activity.from_property.id if activity.from_property else None,
            group_id=self._resolve_group(activity),
            reply_context={"conversation_reference": json.dumps(reference.serialize()), "user_name": user_name},
        )

    async def _on_turn_error(self, turn_context: TurnContext, error: Exception) -> None:
        """Adapter-level fallback so a failure anywhere in parsing still reaches the user."""
        self._log.error(f"Unhandled error in Teams turn: {error}")
        await self._send(turn_context, "Sorry, an error occurred while processing your request.")

    async def _send(self, turn_context: TurnContext, text: str) -> None:
        """Send a status message, logging rather than raising when Teams refuses it."""
        try:
            await turn_context.send_activity(text)
        except Exception as e:
            self._log.error(f"Could not send a message to Teams: {e}")

    def _strip_mentions(self, activity: Activity) -> str:
        """Remove the bot's own @mention from the message text.

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
        """Best guess at an attachment's real media type from the activity alone.

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
        requests: List[AgentRequest],
        tenant_id: Optional[str],
    ) -> Tuple[List[str], List[str], List[str], List[str]]:
        """Download Teams attachments (images and files) and append them to ``requests``.

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
        """Build the Authorization header for an attachment URL.

        A bearer is only ever sent to a host whose audience it was minted for; an
        unrecognised host is fetched without one rather than being handed a token.

        :raises PermissionError: when the host needs a token that cannot be obtained.
        """
        if any(param in content_url for param in PRE_AUTH_PARAMS):
            return {}

        host = (urlparse(content_url).hostname or "").lower()

        if any(host == suffix or host.endswith(f".{suffix}") for suffix in CONNECTOR_HOST_SUFFIXES):
            token = await self._credentials.bot_framework_token()
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

        result = await asyncio.to_thread(self._credentials.acquire_token, tenant_id, scope)
        if "access_token" not in result:
            raise PermissionError(
                f"token request for {scope} in tenant {tenant_id} failed: {result.get('error')} - {result.get('error_description')}"
            )
        return {"Authorization": f"Bearer {result['access_token']}"}

    async def _download(self, content_url: str, headers: Dict[str, str]) -> Tuple[Optional[bytes], Optional[str]]:
        """Stream an attachment, aborting as soon as it exceeds api.max_file_size.

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


class TeamsOutboundAdapter(OutboundAdapter):
    """Agent replies -> Teams activities, delivered proactively."""

    name = NAME
    # Teams drops oversized activities outright, so a long reply is split rather than trimmed.
    MESSAGE_LIMIT = MAX_MESSAGE_LENGTH

    _log = logging.getLogger("ak.integration.teams")

    def __init__(self):
        self._acknowledgement = AKConfig.get().teams.agent_acknowledgement or None
        self._credentials = _TeamsCredentials()

    async def acknowledge(self, reply_context: Dict[str, str]) -> Dict[str, str]:
        if self._acknowledgement:
            await self._send(reply_context, f"Hi {reply_context.get('user_name', 'there')}, {self._acknowledgement}")
        return {}

    async def deliver(self, reply: AgentReply, reply_context: Dict[str, str]) -> None:
        text = str(reply)
        if not text.strip():
            text = "The agent returned an empty response."
        for chunk in self.split_reply(text):
            await self._send(reply_context, chunk, raise_on_failure=True)

    async def deliver_error(self, message: str, reply_context: Dict[str, str]) -> None:
        user_name = reply_context.get("user_name")
        await self._send(reply_context, f"Sorry {user_name}, {message[0].lower()}{message[1:]}" if user_name else message)

    async def _send(self, reply_context: Dict[str, str], text: str, raise_on_failure: bool = False) -> None:
        """Send one activity into the conversation the request came from.

        Proactive delivery is the only option from here: this process never held the turn that
        received the message, so it re-enters the conversation through its reference.
        """
        reference = ConversationReference.deserialize(json.loads(reply_context["conversation_reference"]))

        async def _callback(turn_context: TurnContext) -> None:
            await turn_context.send_activity(text)

        try:
            await self._credentials.adapter.continue_conversation(reference, _callback, self._credentials.app_id)
        except Exception as e:
            self._log.error(f"Failed to continue the Teams conversation: {e}")
            if raise_on_failure:
                # Raising buys the ConsumerLoop's retries; a status message is best effort.
                raise
