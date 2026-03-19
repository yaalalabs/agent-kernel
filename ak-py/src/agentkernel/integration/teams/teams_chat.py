import base64
import io
import logging
import re
import traceback
from typing import List

import httpx
import msal
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity, ActivityTypes, Attachment
from fastapi import APIRouter, HTTPException, Request, Response

from ...api import RESTRequestHandler
from ...core import AgentService, Config
from ...core.model import (
    AgentReply,
    AgentReplyImage,
    AgentReplyText,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
)


class AgentTeamsRequestHandler(RESTRequestHandler):
    """
    API routers that expose endpoints to interact with Microsoft Teams using Agent Kernel.

    This handler uses Azure Bot Framework to receive messages and send responses.
    Supports text, images, and files like WhatsApp/Messenger/Slack integrations.

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

        if not self._app_id or not self._app_password:
            self._log.error("Teams configuration is incomplete. Please set app_id and app_password.")
            raise ValueError("Incomplete Teams configuration.")

        if self._tenant_id:
            self._log.info(f"Using Teams App ID: {self._app_id} with Tenant ID: {self._tenant_id}")
            self._msal_authority = f"https://login.microsoftonline.com/{self._tenant_id}"
        else:
            self._log.info(f"Using Teams App ID: {self._app_id} (Multi Tenant)")
            self._msal_authority = "https://login.microsoftonline.com/common"

        # Initialize Bot Framework Adapter
        settings = BotFrameworkAdapterSettings(self._app_id, self._app_password, channel_auth_tenant=self._tenant_id)
        self._adapter = BotFrameworkAdapter(settings)

        # Initialize MSAL Application for Graph access
        self._msal_app = msal.ConfidentialClientApplication(
            self._app_id,
            authority=self._msal_authority,
            client_credential=self._app_password,
        )

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
            try:
                import json

                body_text = (await request.body()).decode("utf-8")
                auth_header = request.headers.get("Authorization", "")

                self._log.debug(f"Received Teams message, auth header present: {bool(auth_header)}")

                # Bot Framework expects a dict with 'body' as parsed JSON
                req_dict = {"body": json.loads(body_text), "headers": {"Authorization": auth_header}}  # Parse JSON

                # Process the activity using Bot Framework adapter
                async def bot_logic(turn_context: TurnContext):
                    await self._handle_teams_message(turn_context)

                # Process the request - Bot Framework validates auth internally
                await self._adapter.process_activity(req_dict, auth_header, bot_logic)
                return Response(status_code=200)

            except Exception as e:
                self._log.error(f"Error processing Teams message: {str(e)}\n{traceback.format_exc()}")
                raise HTTPException(status_code=500, detail="Internal server error")

        return router

    async def _handle_teams_message(self, turn_context: TurnContext):
        """
        Process incoming Teams message and send response.
        """
        activity: Activity = turn_context.activity

        # Only handle message activities
        if activity.type != ActivityTypes.message:
            return

        # Get message details
        text = activity.text or ""
        conversation_id = activity.conversation.id
        user_name = activity.from_property.name if activity.from_property else "User"

        # Remove bot mentions from text
        text = self._remove_mentions(text, activity.recipient.id if activity.recipient else None)
        text = text.strip()

        # Skip empty messages
        if not text and not activity.attachments:
            return

        self._log.info(f"Received Teams message from {user_name}: {text[:100]}")

        service = AgentService()
        try:
            # Send acknowledgement if configured
            if self._teams_agent_acknowledgement:
                await turn_context.send_activity(f"Hi {user_name}, {self._teams_agent_acknowledgement}")

            # Select agent
            service.select(session_id=conversation_id, name=self._teams_agent)
            if not service.agent:
                await turn_context.send_activity("No agent available to handle your request.")
                return

            # Build requests list with text, files, and images
            requests = []
            if text:
                requests.append(AgentRequestText(text=text))

            # Process attachments (images and files)
            if activity.attachments:
                failed_files = await self._process_attachments(activity.attachments, requests)
                if failed_files:
                    await turn_context.send_activity(
                        f"Sorry {user_name}, I could not download the following files: {', '.join(failed_files)}. Please try again."
                    )
                    return

            # Invoke agent
            reply = await service.run_multi(requests)

            # Send reply
            await self._send_reply(turn_context, reply, user_name)

        except Exception as e:
            self._log.error(f"Error processing agent message: {str(e)}\n{traceback.format_exc()}")
            await turn_context.send_activity(f"Sorry {user_name}, an error occurred while processing your request.")

    def _remove_mentions(self, text: str, bot_id: str = None) -> str:
        """Remove @mentions from text."""
        # Remove <at>bot</at> mentions
        text = re.sub(r"<at>.*?</at>", "", text)
        # Remove plain @mentions
        text = re.sub(r"@\w+", "", text)
        return text.strip()

    async def _process_attachments(self, attachments: List[Attachment], requests: List) -> List[str]:
        """
        Process Teams attachments (images and files).
        Returns list of failed file names.
        """
        failed_files = []
        rejected_files = []
        oversized_files = []

        for attachment in attachments:
            content_type = attachment.content_type or ""
            name = attachment.name or "file"
            content_url = attachment.content_url

            # Handle Teams file attachments which have downloadUrl in content
            if content_type == "application/vnd.microsoft.teams.file.download.info":
                # content is a dict-like object (or dict)
                if attachment.content and isinstance(attachment.content, dict):
                    # Always prefer the downloadUrl from content if available as it often contains tempauth
                    download_url_from_content = attachment.content.get("downloadUrl")
                    if download_url_from_content:
                        content_url = download_url_from_content

            if not content_url:
                # Ignore text/html attachments (usually the message body)
                if content_type == "text/html":
                    continue

                self._log.warning(f"Attachment '{name}' has no content URL. Type: '{content_type}'.")
                failed_files.append(name)
                continue

            # Reject audio/video files
            if content_type.startswith(("audio/", "video/")):
                rejected_files.append(name)
                continue

            file_data = None
            download_success = False

            # Try Direct Download from content_url
            try:
                headers = {}

                # Check if content_url has tempauth, if so we likely don't need extra headers
                has_tempauth = "tempauth=" in content_url if content_url else False

                if content_type == "application/vnd.microsoft.teams.file.download.info" and not has_tempauth:
                    try:
                        # Extract the host from the download URL to determine the correct scope
                        from urllib.parse import urlparse

                        parsed_url = urlparse(content_url)
                        resource_host = parsed_url.netloc
                        hostname = parsed_url.hostname or ""

                        # Construct scope for the specific resource
                        if hostname == "sharepoint.com" or hostname.endswith(".sharepoint.com"):
                            scope = f"https://{resource_host}/.default"
                        else:
                            scope = "https://graph.microsoft.com/.default"

                        result = self._msal_app.acquire_token_for_client(scopes=[scope])

                        if "access_token" in result:
                            token = result["access_token"]
                            headers["Authorization"] = f"Bearer {token}"
                        else:
                            self._log.error(f"Failed to acquire token for {scope}: {result.get('error_description')}")
                    except Exception as e:
                        self._log.error(f"Error getting access token for attachment download: {e}")

                # Download attachment
                async with httpx.AsyncClient() as client:
                    response = await client.get(content_url, headers=headers, timeout=30.0)
                    if response.status_code == 200:
                        file_data = response.content
                        download_success = True
                        # Update content_type from response headers
                        if "content-type" in response.headers:
                            content_type = response.headers["content-type"].split(";")[0].strip()
                    else:
                        self._log.warning(f"Direct download failed with status {response.status_code}.")

            except Exception as e:
                self._log.warning(f"Direct download attempt failed for {name}: {str(e)}")

            if not download_success:
                failed_files.append(name)
                continue

            try:
                # Verify file size
                file_size = len(file_data)
                if file_size > self._max_file_size:
                    oversized_files.append(f"{name} ({file_size / (1024 * 1024):.2f} MB)")
                    continue

                # Add to requests based on type
                if content_type.startswith("image/"):
                    requests.append(AgentRequestImage(image_data=base64.b64encode(file_data).decode("utf-8"), name=name, mime_type=content_type))
                    self._log.info(f"Image {name} added to request")
                else:
                    requests.append(AgentRequestFile(file_data=base64.b64encode(file_data).decode("utf-8"), name=name, mime_type=content_type))
                    self._log.info(f"File {name} added to request")
            except Exception as e:
                self._log.error(f"Error processing downloaded content for {name}: {e}")
                failed_files.append(name)

        # Return combined list of all failed/rejected files
        return failed_files + rejected_files + oversized_files

    async def _send_reply(self, turn_context: TurnContext, reply: AgentReply, user_name: str):
        """Send agent reply to Teams."""
        try:
            # Standardize reply handling similar to Slack/WhatsApp
            reply_text = str(reply) if isinstance(reply, (AgentReplyText, AgentReplyImage)) else str(reply)

            # Send the text response
            await turn_context.send_activity(reply_text)

        except Exception as e:
            self._log.error(f"Error sending reply to Teams: {e}")
            await turn_context.send_activity("Error sending agent response.")
