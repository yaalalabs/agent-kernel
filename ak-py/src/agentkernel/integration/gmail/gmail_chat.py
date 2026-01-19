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

from ...core import (
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
    AgentService,
    Config,
)


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
            self._log.error("Gmail credentials are not configured. Please set AK_GMAIL__CLIENT_ID and AK_GMAIL__CLIENT_SECRET.")
            raise ValueError("Incomplete Gmail configuration.")

        # Email filtering configuration (optional)
        self._sender_filter = os.environ.get("AK_GMAIL__SENDER_FILTER")  # Comma-separated list of allowed senders
        self._subject_filter = os.environ.get("AK_GMAIL__SUBJECT_FILTER")  # Comma-separated list of subject keywords

        # Parse filters into lists
        self._allowed_senders = [s.strip() for s in self._sender_filter.split(",")] if self._sender_filter else None
        self._subject_keywords = [s.strip() for s in self._subject_filter.split(",")] if self._subject_filter else None

        self._service = None
        self._is_running = False
        self._processed_emails = set()  # Track processed email IDs (prevents processing same email twice)

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

    def _should_process_email(self, message_id: str) -> bool:
        """
        Check if email should be processed based on sender and subject filters.

        :param message_id: Gmail message ID
        :return: True if email passes filter, False otherwise
        """
        if not self._allowed_senders and not self._subject_keywords:
            # No filters configured, process all emails
            return True

        try:
            # Get message headers
            message = self._service.users().messages().get(userId="me", id=message_id, format="full").execute()
            headers = message["payload"]["headers"]
            sender = self._get_header(headers, "From")
            subject = self._get_header(headers, "Subject")

            # Check sender filter
            if self._allowed_senders:
                sender_match = any(allowed in sender for allowed in self._allowed_senders)
                if not sender_match:
                    self._log.debug(f"Email from '{sender}' does not match allowed senders filter")
                    return False

            # Check subject filter
            if self._subject_keywords:
                subject_match = any(keyword.lower() in subject.lower() for keyword in self._subject_keywords)
                if not subject_match:
                    self._log.debug(f"Subject '{subject}' does not contain any keywords filter")
                    return False

            return True

        except Exception as e:
            self._log.warning(f"Error checking email filters: {e}")
            return True  # Default to processing if error occurs

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
            self._log.info(f"[POLLING] Checking for emails with query: {query}")  # Always log polling
            results = self._service.users().messages().list(userId="me", q=query, maxResults=10).execute()

            messages = results.get("messages", [])

            if not messages:
                self._log.info("[POLLING] No new unread emails found")  # Log when nothing found
                return

            self._log.info(f"[POLLING] Found {len(messages)} unread email(s)")

            for msg in messages:
                msg_id = msg["id"]

                # Skip if already processed
                if msg_id in self._processed_emails:
                    self._log.debug(f"Email {msg_id} already processed, skipping")
                    continue

                # Check if email passes filter criteria
                if not self._should_process_email(msg_id):
                    self._log.debug(f"Email {msg_id} filtered out by sender or subject filter")
                    self._processed_emails.add(msg_id)  # Mark as processed anyway
                    continue

                self._log.info(f"[POLLING] Processing email {msg_id}")
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
            message_id_header = self._get_header(headers, "Message-ID")  # Extract Message-ID header for proper threading
            thread_id = message.get("threadId")

            # Extract email body
            body = self._get_email_body(message["payload"])

            if not body:
                self._log.warning(f"Email {message_id} has no body content")
                return

            self._log.info(f"[EMAIL] Processing email - from={sender}, subject={subject}, thread_id={thread_id}, message_id={message_id}")

            # Extract attachments from email
            attachments = self._extract_attachments(message_id, message["payload"])
            if attachments:
                self._log.info(f"[EMAIL] Found {len(attachments)} attachment(s)")

            # Use thread_id as session_id for agent context (threaded conversations)
            session_id = thread_id or sender

            # Fetch thread history for context (all messages in the thread, sorted by internalDate)
            thread_history = await self._get_thread_history(thread_id, message_id)

            # Process through agent with full thread context and attachments
            response = await self._process_with_agent(
                sender, subject, body, session_id=session_id, thread_history=thread_history, attachments=attachments
            )

            if response:
                # Send reply
                self._log.info(f"[SEND_REPLY] thread_id={thread_id}, message_id={message_id}, to={sender}")
                await self._send_reply(message_id_header, thread_id, sender, subject, response)

                # Mark as read
                self._mark_as_read(message_id)

        except Exception as e:
            self._log.error(f"Error processing email {message_id}: {e}\n{traceback.format_exc()}")

    async def _get_thread_history(self, thread_id: Optional[str], current_message_id: str, max_history: int = 5) -> str:
        """
        Fetch recent messages in the same Gmail thread for context.
        Returns a concatenated string of the thread history (last N messages, excluding current).

        :param thread_id: Gmail thread ID
        :param current_message_id: Current message ID (to skip)
        :param max_history: Maximum number of previous messages to include (default: 5)
        """
        if not thread_id:
            return ""
        try:
            thread = self._service.users().threads().get(userId="me", id=thread_id, format="full").execute()
            messages = thread.get("messages", [])
            # Sort by internalDate (ascending, oldest first)
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

            # Keep only last max_history messages
            recent_history = history[-max_history:] if len(history) > max_history else history
            result = "\n".join(recent_history)
            return result
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
        Handles both single-part and multipart messages.
        Prioritizes plain text, falls back to HTML, then returns empty if neither.
        Recursively searches nested multipart structures.

        :param payload: Email payload
        :return: Email body text
        """
        body = ""

        # Handle multipart messages (most common)
        if "parts" in payload:
            for part in payload["parts"]:
                mime_type = part.get("mimeType", "")

                # Priority 1: Get plain text if available
                if mime_type == "text/plain":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        try:
                            body = base64.urlsafe_b64decode(data).decode("utf-8")
                            return body  # Return immediately if we found plain text
                        except Exception as e:
                            self._log.warning(f"Error decoding plain text: {e}")

                # Priority 2: Fall back to HTML if no plain text found yet
                elif mime_type == "text/html" and not body:
                    data = part.get("body", {}).get("data", "")
                    if data:
                        try:
                            body = base64.urlsafe_b64decode(data).decode("utf-8")
                        except Exception as e:
                            self._log.warning(f"Error decoding HTML: {e}")

                # Priority 3: Recursively handle nested multipart structures
                elif mime_type.startswith("multipart/") and not body:
                    nested_body = self._get_email_body(part)
                    if nested_body:
                        return nested_body
        else:
            # Handle single-part messages
            data = payload.get("body", {}).get("data", "")
            if data:
                try:
                    body = base64.urlsafe_b64decode(data).decode("utf-8")
                except Exception as e:
                    self._log.warning(f"Error decoding message body: {e}")

        return body.strip() if body else ""

    async def _process_with_agent(
        self,
        sender: str,
        subject: str,
        body: str,
        session_id: Optional[str] = None,
        thread_history: Optional[str] = None,
        attachments: list = None,
    ) -> Optional[str]:
        """
        Process email through AI agent.

        :param sender: Email sender
        :param subject: Email subject
        :param body: Email body
        :param session_id: Session ID for agent context (use threadId for threading)
        :param thread_history: Full thread history for context
        :param attachments: List of AgentRequestImage or AgentRequestFile objects
        :return: AI-generated response or None
        """
        if attachments is None:
            attachments = []

        service = AgentService()
        session_id = session_id or sender

        try:
            # Format email content for agent, including thread history if available
            if thread_history:
                email_content = f"Thread history:\n{thread_history}\n\nNew message:\nFrom: {sender}\nSubject: {subject}\n\n{body}"
            else:
                email_content = f"From: {sender}\nSubject: {subject}\n\n{body}"

            # Select agent
            service.select(session_id=session_id, name=self._gmail_agent)
            if not service.agent:
                self._log.warning(f"No agent available for name: {self._gmail_agent}")
                return None

            # Build request list: text first, then attachments
            requests = [AgentRequestText(text=email_content)]
            requests.extend(attachments)

            # Log request summary
            self._log.info(f"[AGENT_INPUT] Total requests: {len(requests)}")

            # Run the agent with all requests
            if len(requests) > 1:
                # Multiple requests (text + attachments) - use run_multi
                self._log.info(f"[AGENT_CALL] Running agent with {len(requests)} request(s) (text + {len(attachments)} attachment(s))")
                result = await service.run_multi(requests)
            else:
                # Only text - use standard run
                self._log.info(f"[AGENT_CALL] Running agent with text only")
                result = await service.run(email_content)

            # Extract response text
            if hasattr(result, "raw"):
                response_text = str(result.raw)
            else:
                response_text = str(result)

            return response_text

        except Exception as e:
            self._log.error(f"Error processing with agent: {e}\n{traceback.format_exc()}")
            return None

    async def _send_reply(self, original_message_id_header: str, thread_id: str, to: str, subject: str, body: str):
        """
        Send email reply.
        Skips in test mode (when self._service is None).
        :param original_message_id_header: Original email's Message-ID header (for proper threading)
        :param thread_id: Thread ID for threading
        :param to: Recipient email
        :param subject: Email subject
        :param body: Email body from agent
        """
        if self._service is None:
            self._log.info("Test mode: Skipping send reply.")
            return
        try:
            # Clean up agent response: remove "Subject: ..." line if present
            reply_body = body

            # Add signature with configurable format and name (if configured)
            client_name = os.environ.get("AK_CLIENT_NAME")
            sign_off = os.environ.get("AK_GMAIL_SIGN_OFF")  # Best regards, Sincerely, Kind regards, etc.

            signature_lines = []
            if sign_off:
                # Preserve existing comma placement when both sign-off and name are present
                if client_name:
                    signature_lines.append(f"{sign_off},")
                else:
                    signature_lines.append(sign_off)
            if client_name:
                signature_lines.append(client_name)
            if signature_lines:
                reply_body = f"{reply_body}\n\n" + "\n".join(signature_lines)

            # Create message
            message = MIMEText(reply_body)
            message["to"] = to
            message["subject"] = subject
            # Add In-Reply-To header to properly link messages in Gmail thread
            if original_message_id_header:
                message["In-Reply-To"] = original_message_id_header
                message["References"] = original_message_id_header

            # Encode message
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

            # Send with thread ID to maintain conversation threading
            send_message = {"raw": raw_message, "threadId": thread_id}

            self._log.info(f"[SEND_REPLY] Sending reply with threadId={thread_id}, to={to}, subject={subject}")

            result = self._service.users().messages().send(userId="me", body=send_message).execute()

            self._log.info(f"[SEND_REPLY] Reply sent successfully (message ID: {result['id']}, threadId: {thread_id})")

        except Exception as e:
            self._log.error(f"Error sending reply: {e}\n{traceback.format_exc()}")

    def _extract_attachments(self, message_id: str, payload: dict) -> list:
        """
        Extract attachments from email message.

        :param message_id: Gmail message ID
        :param payload: Message payload containing parts
        :return: List of AgentRequestImage or AgentRequestFile objects
        """
        attachments = []

        if self._service is None:
            self._log.info("Test mode: Skipping attachment extraction.")
            return attachments

        try:
            # Check for parts (multipart message)
            parts = payload.get("parts", [])

            for part in parts:
                # Skip inline/text parts
                if part.get("filename") == "":
                    continue

                filename = part.get("filename", "unknown")
                mime_type = part.get("mimeType", "application/octet-stream")

                # Get attachment ID
                part_id = part.get("partId")
                if not part_id:
                    continue

                try:
                    # Download attachment data
                    attachment_data = (
                        self._service.users()
                        .messages()
                        .attachments()
                        .get(userId="me", messageId=message_id, id=part.get("body", {}).get("attachmentId"))
                        .execute()
                    )

                    if "data" not in attachment_data:
                        self._log.warning(f"No data in attachment: {filename}")
                        continue

                    # Gmail API returns URL-safe base64, but OpenAI expects standard base64
                    urlsafe_data = attachment_data["data"]
                    data = base64.b64encode(base64.urlsafe_b64decode(urlsafe_data)).decode("utf-8")

                    # Validate MIME type is set
                    if not mime_type or mime_type == "application/octet-stream":
                        # Try to infer MIME type from filename extension
                        if filename:
                            ext = filename.lower().split(".")[-1]
                            mime_map = {
                                "pdf": "application/pdf",
                                "doc": "application/msword",
                                "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                "xls": "application/vnd.ms-excel",
                                "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                "jpg": "image/jpeg",
                                "jpeg": "image/jpeg",
                                "png": "image/png",
                                "gif": "image/gif",
                                "webp": "image/webp",
                            }
                            inferred_mime = mime_map.get(ext)
                            if inferred_mime:
                                self._log.info(f"Inferred MIME type for {filename}: {inferred_mime} (from extension .{ext})")
                                mime_type = inferred_mime
                            else:
                                self._log.warning(f"Could not infer MIME type for extension .{ext}")

                    # Create appropriate request based on MIME type
                    # Use base64 string (AgentRequest* objects expect base64-encoded strings, not binary)
                    if mime_type.startswith("image/"):
                        request = AgentRequestImage(image_data=data, name=filename, mime_type=mime_type)
                        attachments.append(request)
                        self._log.debug(f"Extracted image attachment: {filename} ({mime_type})")

                    elif mime_type in [
                        "application/pdf",
                        "application/msword",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        "application/vnd.ms-excel",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ]:
                        # Handle document attachments (PDF, Word, Excel)
                        request = AgentRequestFile(file_data=data, name=filename, mime_type=mime_type)
                        attachments.append(request)
                        self._log.debug(f"Extracted file attachment: {filename} ({mime_type})")

                    else:
                        self._log.debug(f"Skipping unsupported attachment type: {mime_type}")

                except Exception as e:
                    self._log.warning(f"Error extracting attachment {filename}: {e}")
                    continue

            if attachments:
                self._log.info(f"Extracted {len(attachments)} attachment(s) from message {message_id}")

        except Exception as e:
            self._log.warning(f"Error processing attachments: {e}")

        return attachments

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
            self._service.users().messages().modify(userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}).execute()

        except Exception as e:
            self._log.warning(f"Error marking email as read: {e}")
