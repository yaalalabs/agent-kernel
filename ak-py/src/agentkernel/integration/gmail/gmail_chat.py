import asyncio
import base64
import logging
import os
import pickle
import traceback
from email.mime.text import MIMEText
from typing import Optional

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from ...core import AgentService, Config


class AgentGmailRequestHandler:
    """
    Gmail integration handler for Agent Kernel.

    This handler uses Gmail API with OAuth2 to:
    - Poll for new emails
    - Process emails through AI agent
    - Send AI-generated replies

    Features:
    - OAuth2 authentication
    - Polling-based email checking
    - Email threading support
    - Unread email tracking
    - Reply generation
    """

    # Gmail API scopes needed
    SCOPES = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.modify",
    ]

    def __init__(self):
        self._log = logging.getLogger("ak.api.gmail")

        # Load configuration
        self._gmail_agent = Config.get().gmail.agent if Config.get().gmail.agent != "" else None
        self._token_file = Config.get().gmail.token_file or "token.pickle"
        self._poll_interval = Config.get().gmail.poll_interval or 30
        self._label_filter = Config.get().gmail.label_filter or "INBOX"

        # Read credentials from environment variables
        self._client_id = os.environ.get("AK_GMAIL__CLIENT_ID")
        self._client_secret = os.environ.get("AK_GMAIL__CLIENT_SECRET")
        self._redirect_uris = os.environ.get("AK_GMAIL__REDIRECT_URIS", "http://localhost").split(",")
        if not (self._client_id and self._client_secret):
            self._log.error(
                "Gmail credentials are not configured. Please set AK_GMAIL__CLIENT_ID and AK_GMAIL__CLIENT_SECRET."
            )
            raise ValueError("Incomplete Gmail configuration.")

        self._service = None
        self._is_running = False
        self._processed_emails = set()  # Track processed email IDs

    def authenticate(self):
        """
        Authenticate with Gmail API using OAuth2.
        Skips authentication if AK_TEST_MODE=1 is set in the environment.
        """
        if os.environ.get("AK_TEST_MODE") == "1":
            self._log.info("Test mode enabled: Skipping Gmail authentication.")
            self._service = None
            return

        creds = None
        # Load existing credentials if available
        if os.path.exists(self._token_file):
            with open(self._token_file, "rb") as token:
                creds = pickle.load(token)

        # If credentials are invalid or don't exist, authenticate
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                self._log.info("Refreshing expired credentials...")
                creds.refresh(Request())
            else:
                self._log.info("Starting OAuth2 flow with environment variables...")
                # Build credentials dict as expected by InstalledAppFlow
                client_config = {
                    "installed": {
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "redirect_uris": self._redirect_uris,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                    }
                }
                flow = InstalledAppFlow.from_client_config(client_config, self.SCOPES)
                creds = flow.run_local_server(port=0)

            # Save credentials for future use
            with open(self._token_file, "wb") as token:
                pickle.dump(creds, token)
            self._log.info(f"Credentials saved to {self._token_file}")

        # Build Gmail service
        self._service = build("gmail", "v1", credentials=creds)
        self._log.info("Gmail API authentication successful")

    async def start_polling(self):
        """
        Start polling for new emails.

        Runs in background loop, checking for new emails at configured interval.
        """
        if not self._service:
            self.authenticate()

        self._is_running = True
        self._log.info(f"Starting email polling (interval: {self._poll_interval}s, label: {self._label_filter})")

        while self._is_running:
            try:
                await self._check_new_emails()
                await asyncio.sleep(self._poll_interval)
            except Exception as e:
                self._log.error(f"Error in polling loop: {e}\n{traceback.format_exc()}")
                await asyncio.sleep(self._poll_interval)

    def stop_polling(self):
        """Stop the polling loop."""
        self._is_running = False
        self._log.info("Stopping email polling")

    async def _check_new_emails(self):
        """
        Check for new unread emails.
        Skips in test mode (when self._service is None).
        """
        if self._service is None:
            self._log.info("Test mode: Skipping email check.")
            return
        try:
            # Query for unread emails
            query = f"is:unread label:{self._label_filter}"
            results = self._service.users().messages().list(userId="me", q=query, maxResults=10).execute()

            messages = results.get("messages", [])

            if not messages:
                self._log.debug("No new unread emails")
                return

            self._log.info(f"Found {len(messages)} unread email(s)")

            for msg in messages:
                msg_id = msg["id"]

                # Skip if already processed
                if msg_id in self._processed_emails:
                    continue

                # Process the email
                await self._process_email(msg_id)

                # Mark as processed
                self._processed_emails.add(msg_id)

        except Exception as e:
            self._log.error(f"Error checking emails: {e}\n{traceback.format_exc()}")

    async def _process_email(self, message_id: str):
        """
        Process a single email.
        Skips in test mode (when self._service is None).
        :param message_id: Gmail message ID
        """
        if self._service is None:
            self._log.info("Test mode: Skipping email processing.")
            return
        try:
            # Get full message details
            message = self._service.users().messages().get(userId="me", id=message_id, format="full").execute()

            # Extract email details
            headers = message["payload"]["headers"]
            subject = self._get_header(headers, "Subject")
            sender = self._get_header(headers, "From")
            thread_id = message.get("threadId")

            # Extract email body
            body = self._get_email_body(message["payload"])

            if not body:
                self._log.warning(f"Email {message_id} has no body content")
                return

            self._log.info(f"Processing email from {sender}, subject: {subject}")
            self._log.debug(f"Email body: {body[:200]}...")

            # Use thread_id as session_id for agent context (threaded conversations)
            session_id = thread_id or sender

            # Fetch thread history for context (all messages in the thread, sorted by internalDate)
            thread_history = await self._get_thread_history(thread_id, message_id)

            # Process through agent with full thread context
            response = await self._process_with_agent(
                sender, subject, body, session_id=session_id, thread_history=thread_history
            )

            if response:
                # Send reply
                await self._send_reply(message_id, thread_id, sender, subject, response)

                # Mark as read
                self._mark_as_read(message_id)

        except Exception as e:
            self._log.error(f"Error processing email {message_id}: {e}\n{traceback.format_exc()}")

    async def _get_thread_history(self, thread_id: Optional[str], current_message_id: str) -> str:
        """
        Fetch all previous messages in the same Gmail thread for context.
        Returns a concatenated string of the thread history (excluding the current message).
        """
        if not thread_id:
            return ""
        try:
            thread = self._service.users().threads().get(userId="me", id=thread_id, format="full").execute()
            messages = thread.get("messages", [])
            # Sort by internalDate (ascending)
            messages = sorted(messages, key=lambda m: int(m.get("internalDate", "0")))
            history = []
            for msg in messages:
                if msg["id"] == current_message_id:
                    continue  # skip the current message (will be processed separately)
                headers = msg["payload"]["headers"]
                from_addr = self._get_header(headers, "From")
                subject = self._get_header(headers, "Subject")
                date = self._get_header(headers, "Date")
                body = self._get_email_body(msg["payload"])
                if body:
                    history.append(f"From: {from_addr}\nDate: {date}\nSubject: {subject}\n\n{body}\n{'-'*40}")
            return "\n".join(history)
        except Exception as e:
            self._log.warning(f"Error fetching thread history: {e}\n{traceback.format_exc()}")
            return ""

    def _get_header(self, headers: list, name: str) -> Optional[str]:
        """
        Get email header value.

        :param headers: List of header objects
        :param name: Header name
        :return: Header value or None
        """
        for header in headers:
            if header["name"].lower() == name.lower():
                return header["value"]
        return None

    def _get_email_body(self, payload: dict) -> str:
        """
        Extract email body from payload.

        :param payload: Email payload
        :return: Email body text
        """
        body = ""

        if "parts" in payload:
            # Multipart message
            for part in payload["parts"]:
                if part["mimeType"] == "text/plain":
                    data = part["body"].get("data")
                    if data:
                        body = base64.urlsafe_b64decode(data).decode("utf-8")
                        break
                elif part["mimeType"] == "text/html" and not body:
                    # Fallback to HTML if no plain text
                    data = part["body"].get("data")
                    if data:
                        body = base64.urlsafe_b64decode(data).decode("utf-8")
        else:
            # Single part message
            data = payload["body"].get("data")
            if data:
                body = base64.urlsafe_b64decode(data).decode("utf-8")

        return body.strip()

    async def _process_with_agent(
        self,
        sender: str,
        subject: str,
        body: str,
        session_id: Optional[str] = None,
        thread_history: Optional[str] = None,
    ) -> Optional[str]:
        """
        Process email through AI agent.

        :param sender: Email sender
        :param subject: Email subject
        :param body: Email body
        :param session_id: Session ID for agent context (use threadId for threading)
        :param thread_history: Full thread history for context
        :return: AI-generated response or None
        """
        service = AgentService()
        session_id = session_id or sender

        try:
            # Format email content for agent, including thread history if available
            if thread_history:
                email_content = (
                    f"Thread history:\n{thread_history}\n\nNew message:\nFrom: {sender}\nSubject: {subject}\n\n{body}"
                )
            else:
                email_content = f"From: {sender}\nSubject: {subject}\n\n{body}"

            # Select and run agent
            service.select(session_id=session_id, name=self._gmail_agent)
            if not service.agent:
                self._log.warning(f"No agent available for name: {self._gmail_agent}")
                return None

            # Run the agent
            result = await service.run(email_content)

            if hasattr(result, "raw"):
                response_text = str(result.raw)
            else:
                response_text = str(result)

            self._log.debug(f"Agent response: {response_text[:200]}...")
            return response_text

        except Exception as e:
            self._log.error(f"Error processing with agent: {e}\n{traceback.format_exc()}")
            return None

    async def _send_reply(self, original_message_id: str, thread_id: str, to: str, subject: str, body: str):
        """
        Send email reply.
        Skips in test mode (when self._service is None).
        :param original_message_id: Original message ID
        :param thread_id: Thread ID for threading
        :param to: Recipient email
        :param subject: Email subject (will add Re: if needed)
        :param body: Email body
        """
        if self._service is None:
            self._log.info("Test mode: Skipping send reply.")
            return
        try:
            # Add "Re: " to subject if not already there
            if not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"

            # Only reply with the subject and the body, and append 'Best regards, <client name>'
            client_name = os.environ.get("AK_CLIENT_NAME", "Agent Kernel")
            reply_body = f"{body}\n\nBest regards,\n{client_name}"

            # Create message
            message = MIMEText(reply_body)
            message["to"] = to
            message["subject"] = subject

            # Encode message
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

            # Send with thread ID to maintain conversation threading
            send_message = {"raw": raw_message, "threadId": thread_id}

            result = self._service.users().messages().send(userId="me", body=send_message).execute()

            self._log.info(f"Reply sent successfully (message ID: {result['id']})")

        except Exception as e:
            self._log.error(f"Error sending reply: {e}\n{traceback.format_exc()}")

    def _mark_as_read(self, message_id: str):
        """
        Mark email as read.
        Skips in test mode (when self._service is None).
        :param message_id: Gmail message ID
        """
        if self._service is None:
            self._log.info("Test mode: Skipping mark as read.")
            return
        try:
            self._service.users().messages().modify(
                userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}
            ).execute()

            self._log.debug(f"Marked email {message_id} as read")

        except Exception as e:
            self._log.warning(f"Error marking email as read: {e}")
