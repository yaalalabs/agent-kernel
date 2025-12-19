# Gmail Integration

Gmail API integration for Agent Kernel using OAuth2 and email polling.

The `AgentGmailHandler` class handles email conversations with agents via Gmail API. This integration uses the official Google Gmail API (https://developers.google.com/gmail/api) with OAuth2 authentication.

## How It Works

1. OAuth2 authentication flow establishes Gmail access
2. The handler polls for new unread emails at configurable intervals
3. Email content is extracted and passed to your chosen Agent
4. The Agent response is sent back as an email reply
5. Processed emails are marked as read to avoid reprocessing

## Gmail API Setup

### Prerequisites

1. A Google Cloud Console account
2. A Gmail account
3. OAuth2 credentials configured

### Configuration Steps

1. **Create a Google Cloud Project**

   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project
   - Enable the Gmail API
2. **Configure OAuth2 Credentials**

   - Go to APIs & Services > Credentials
   - Create OAuth 2.0 Client ID (Desktop application type)
   - Download the credentials JSON file

3. **Configure OAuth Consent Screen**

   - Set up the OAuth consent screen
   - Add required scopes: `gmail.readonly`, `gmail.send`, `gmail.modify`
   - Add test users if in testing mode

### Required Environment Variables 

Set the following environment variables with your Google Cloud OAuth2 credentials:

```bash
# OAuth2 Credentials (REQUIRED)
export AK_GMAIL__CLIENT_ID="your-google-client-id"
export AK_GMAIL__CLIENT_SECRET="your-google-client-secret"

# Optional Configuration
export AK_GMAIL__REDIRECT_URIS="http://localhost"  # Default: http://localhost
export AK_GMAIL__TOKEN_FILE="token.pickle"         # Default: token.pickle
export AK_GMAIL__POLL_INTERVAL="30"                # Default: 30 seconds
export AK_GMAIL__AGENT="general"                   # Agent name to handle emails
export AK_GMAIL__LABEL_FILTER="INBOX"              # Gmail label to monitor

# Email Signature Customization
export AK_CLIENT_NAME="Your Name"                  # Name to sign replies with
export AK_GMAIL_SIGN_OFF="Best regards"            # Sign-off format (e.g., "Sincerely", "Kind regards")
```


### OAuth Flow

On first run, the handler will:

1. Open a browser for Google OAuth consent
2. Request permissions to read/send emails
3. Save the token for future use

## Simple Gmail Integration Code

```python
from agents import Agent as OpenAIAgent
from agentkernel.openai import OpenAIModule
from agentkernel.gmail import AgentGmailRequestHandler
import asyncio

# Create your agent
general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries via email. Give clear and professional responses.",
)

# Initialize module with agent
OpenAIModule([general_agent])

if __name__ == "__main__":
    handler = AgentGmailRequestHandler()

    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            asyncio.set_event_loop(asyncio.new_event_loop())
            asyncio.run(handler.start_polling())
        else:
            loop.run_until_complete(handler.start_polling())

    except RuntimeError:
        asyncio.run(handler.start_polling())
```

## Configuration Options

### config.yaml

```yaml
gmail:
    agent: "general"  # Name of the agent to handle emails
    poll_interval: 30  # Seconds between polling for new emails
```

## Features

### Supported Email Features

- **Plain Text Emails**: Standard text email content
- **HTML Emails**: HTML content is converted to plain text
- **Email Threading**: Replies maintain conversation thread with full context
- **Thread Support**: Each Gmail thread maintains a separate conversation session
- **Image Attachments**: JPEG, PNG, GIF, WebP images are extracted and sent to agents
- **File Attachments**: PDF, Word, Excel documents are extracted and sent to agents
- **Custom Signatures**: Configurable email signatures with name and sign-off format

### Supported Attachment Types

**Images:**

- JPEG (.jpg, .jpeg) - `image/jpeg`
- PNG (.png) - `image/png`
- GIF (.gif) - `image/gif`
- WebP (.webp) - `image/webp`

**Documents:**

- PDF (.pdf) - `application/pdf`
- Microsoft Word (.doc, .docx)
- Microsoft Excel (.xls, .xlsx)

Attachments are automatically:

1. Downloaded from Gmail API
2. Converted from URL-safe base64 to standard base64
3. Passed to the AI agent as `AgentRequestImage` or `AgentRequestFile` objects

### Email Handling

- **Automatic Polling**: Configurable interval for checking new emails
- **Read Status**: Processed emails are marked as read
- **Session Management**: Uses email thread ID for conversation context
- **Reply Threading**: Responses are threaded to original email

### Security

- **OAuth2 Authentication**: Secure Google OAuth2 flow
- **Token Refresh**: Automatic token refresh when expired
- **Scoped Access**: Only requests necessary Gmail permissions

## Testing

### Local Development

1. Set up Google Cloud project and OAuth credentials
2. Run the handler - browser will open for OAuth consent
3. Send a test email to the configured Gmail account
4. Check logs for email processing

### Testing Steps

1. Set environment variables for your Google Cloud OAuth2 credentials (see above)
2. Start your server
3. Complete OAuth flow in browser
4. Send an email to the Gmail account
5. Wait for poll interval
6. Check response email

## Email Threading & Conversation Context

Each Gmail thread maintains its own conversation session:

- Thread ID is used as the session ID
- Full thread history (last 5 messages) is passed to the agent for context
- Agent responds with full conversation awareness
- Replies are threaded to maintain Gmail's conversation view

### Example Thread Flow

```
Thread ID: 19b2b440cef8d49c

Message 1 (User): "What is a Graph Neural Network?"
  ↓ (processed by agent, context: no history)
  → Reply: "A Graph Neural Network (GNN) is..."

Message 2 (User): "Can you give an example?"
  ↓ (processed by agent, context: previous message)
  → Reply: "Sure! Here's an example of GNN usage..."
```

## Advanced Usage

### Custom Email Handling

You can extend the handler for custom behavior:

```python
from agentkernel.gmail import AgentGmailRequestHandler

class CustomGmailHandler(AgentGmailRequestHandler):
    async def _process_email(self, email: dict):
        subject = email.get("subject", "")
  
        # Custom logic here
        if "[AUTO-REPLY]" in subject:
            return  # Skip auto-replies
  
        # Call parent handler
        await super()._process_email(email)
```

### Filtering Emails

The handler supports filtering emails by sender and/or subject keywords:

```bash
# Only process emails from specific senders (comma-separated)
export AK_GMAIL__SENDER_FILTER="user@example.com,support@company.com"

# Only process emails with specific subject keywords (comma-separated)
export AK_GMAIL__SUBJECT_FILTER="Support,Help,Urgent"

# Use both filters together (requires BOTH to match)
export AK_GMAIL__SENDER_FILTER="support@company.com"
export AK_GMAIL__SUBJECT_FILTER="Support Request,Bug Report"
```

**How filtering works:**

- If `AK_GMAIL__SENDER_FILTER` is set: Only emails from those senders are processed
- If `AK_GMAIL__SUBJECT_FILTER` is set: Only emails with those keywords in subject are processed
- If both are set: Email must match BOTH filters
- If neither is set: All unread emails are processed (default behavior)

## Troubleshooting

### Common Issues

**OAuth flow fails:**

- Ensure environment variables are set correctly (AK_GMAIL__CLIENT_ID, AK_GMAIL__CLIENT_SECRET, etc.)
- Check OAuth consent screen is properly configured
- Verify redirect URIs are set correctly

**Emails not being processed:**

- Check polling is running (look for log messages)
- Verify emails are unread
- Ensure Gmail API is enabled in Google Cloud Console

**Token errors:**

- Delete token.json and re-authenticate
- Check token hasn't been revoked
- Verify OAuth scopes are correct

**Replies not sending:**

- Ensure `gmail.send` scope is authorized
- Check for Gmail sending limits
- Verify email format is correct

### Debug Logging

Enable debug logging to troubleshoot:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## API Rate Limits

Gmail API has rate limits:

- **Daily Quota**: 1,000,000,000 quota units per day
- **Per-User Rate Limit**: 250 quota units per user per second
- **Sending Limit**: 500 emails per day (Gmail), 2000 for Workspace

## References

- [Gmail API Documentation](https://developers.google.com/gmail/api)
- [Gmail API Quickstart](https://developers.google.com/gmail/api/quickstart/python)