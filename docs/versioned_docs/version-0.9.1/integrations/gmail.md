# Gmail Integration

Deploy your Agent Kernel agents as Gmail bots that automatically read and reply to emails using AI. This integration connects your agents directly to Gmail, enabling intelligent email automation for support, sales, and more.

## Overview

The `AgentGmailHandler` bridges Agent Kernel and Gmail. Incoming emails are processed by your agent, which generates and sends replies via Gmail. The integration handles OAuth2 authentication, polling, message parsing, and reply threading.

### How it works:

1. Bot polls Gmail for unread emails
2. New emails are parsed and routed to your agent
3. Agent generates a reply using OpenAI
4. Reply is sent via Gmail, maintaining the thread
5. Email is marked as read

## Key Features

🔐 Secure OAuth2 authentication \
💬 AI-powered email replies \
⚡ Real-time polling and automation \
🔄 Session & conversation management per thread \
📊 Label and filter support \
🎯 Customizable agent instructions \
✉️ Email threading with full context history \
🎨 Custom email signatures and sign-off formats \

## Quick Start

### Prerequisites

- Google Cloud Project with Gmail API enabled
- OAuth2 credentials (client ID and secret from Google Cloud)
- OpenAI API key

### 1. Create Google Cloud Project & Enable Gmail API

- Go to [Google Cloud Console](https://console.cloud.google.com/)
- Create/select a project
- Enable Gmail API in **APIs & Services > Library**

### 2. Create OAuth2 Credentials

- Go to **APIs & Services > Credentials**
- Create OAuth client ID (Desktop app)
- Copy the `client_id` and `client_secret` from the credentials JSON file (no need to save the file)
- Add your Gmail address as a test user in the OAuth consent screen

### 3. Configure Environment Variables

```bash
# OAuth2 Credentials (REQUIRED)
export AK_GMAIL__CLIENT_ID="your-google-client-id"
export AK_GMAIL__CLIENT_SECRET="your-google-client-secret"

# OpenAI Configuration (REQUIRED)
export OPENAI_API_KEY="your_openai_api_key"

# Gmail Configuration (Optional)
export AK_GMAIL__REDIRECT_URIS="http://localhost"  # Default: http://localhost
export AK_GMAIL__AGENT="general"                   # Agent to handle emails
export AK_GMAIL__TOKEN_FILE="token.pickle"        # OAuth token storage
export AK_GMAIL__POLL_INTERVAL="30"               # Polling interval (seconds)
export AK_GMAIL__LABEL_FILTER="INBOX"             # Gmail label to monitor

# Multimodal Configuration (Optional)
export AK_MULTIMODAL__ENABLED=true              # Enable multimodal support (default: false)
export AK_MULTIMODAL__MAX_ATTACHMENTS=20        # Keep last N files in session (default: 20)

# Email Signature Customization 
export AK_CLIENT_NAME="Your Name"                 # Name for signatures
export AK_GMAIL_SIGN_OFF="Best regards"           # Sign-off format
```

**Note:** You do NOT need to provide a credentials.json file. The handler will use these environment variables directly for authentication.

### 4. Configuration File

Edit `config.yaml`:

```yaml
gmail:
  agent: general
  token_file: "token.pickle"
  poll_interval: 30
  label_filter: "INBOX"
```

## Implementation

### Basic Setup

```python
from agents import Agent as OpenAIAgent
from agentkernel.openai import OpenAIModule
from agentkernel.gmail import AgentGmailRequestHandler
import asyncio

general_agent = OpenAIAgent(
    name="general",
    instructions="""You are an AI email assistant.
1. Extract sender's name from the "From:" field
2. Start response with "Hi [Name],"
3. Address their questions professionally
4. Keep it brief (2-3 paragraphs max)
5. Do NOT include "Subject:" or signatures
"""
)

OpenAIModule([general_agent])

if __name__ == "__main__":
    handler = AgentGmailRequestHandler()
    handler.authenticate()
    asyncio.run(handler.start_polling())
```

## Email Threading & Conversation Context

Each Gmail thread maintains its own conversation session:

- **Automatic Threading**: Replies maintain Gmail thread structure
- **Context History**: Agent receives last 5 messages in thread for context
- **Session Management**: Thread ID = conversation session ID
- **Multiple Messages**: Thread can have multiple back-and-forth exchanges

```
Thread: "Product Question"
User:  "How does feature X work?"
       ↓ (Agent gets: no history)
Bot:   "Feature X works by..."

User:  "Can I customize it?"
       ↓ (Agent gets: previous exchange)
Bot:   "Yes! Here are customization options..."
```

## Advanced Usage

### Custom Email Query

The Gmail handler uses a default query (for example, to fetch unread messages). To customize which emails are processed (such as only unread messages from specific senders), configure the handler via your application’s settings or by extending the `AgentGmailHandler` in your own code to use a custom Gmail search query (e.g., `is:unread from:important@example.com`). Refer to the Agent Kernel Gmail integration documentation for the supported configuration options.

### Email Filtering by Sender & Subject

Configure filters via environment variables:

```bash
# Only process emails from specific senders (comma-separated)
export AK_GMAIL__SENDER_FILTER="support@company.com,sales@company.com"

# Only process emails with specific subject keywords (comma-separated)
export AK_GMAIL__SUBJECT_FILTER="Support,Help,Urgent,Bug"

# Use both filters (email must match both to be processed)
export AK_GMAIL__SENDER_FILTER="support@company.com"
export AK_GMAIL__SUBJECT_FILTER="Support Request"
```

### Custom Signature Format

```bash
export AK_CLIENT_NAME="Support Team"
export AK_GMAIL_SIGN_OFF="Warm regards"

# Results in:
# Some response text...
#
# Warm regards,
# Support Team
```

### Auto-Archive After Reply

```python
self._service.users().messages().modify(
    userId='me',
    id=message_id,
    body={'removeLabelIds': ['INBOX']}
).execute()
```

### Process Attachments

```python
def _get_attachments(self, payload: dict):
    attachments = []
    if 'parts' in payload:
        for part in payload['parts']:
            if part.get('filename'):
                attachments.append({
                    'filename': part['filename'],
                    'mimeType': part['mimeType'],
                    'attachmentId': part['body'].get('attachmentId')
                })
    return attachments
```

## Supported Message Types

- Standard emails (text)
- Email threads
- Label-based filtering

## Image & File Attachments

The Gmail integration supports processing email attachments and passing them to your AI agent for analysis.

When `AK_MULTIMODAL__ENABLED=true` is set, the system remembers attachments across the conversation thread, allowing users to ask follow-up questions about files they previously sent. The `analyze_attachments` tool is automatically attached to your agents at startup.

### Supported File Types

| Type                       | Extensions                     | MIME Types                                                          |
| -------------------------- | ------------------------------ | ------------------------------------------------------------------- |
| **Images**           | .jpg, .jpeg, .png, .gif, .webp | image/jpeg, image/png, image/gif, image/webp                        |
| **Documents**        | .pdf                           | application/pdf                                                     |

### How It Works

1. Attachments are automatically extracted from incoming emails
2. MIME types are detected from email metadata or inferred from file extension
3. Files are converted to standard base64 encoding
4. Attachments are passed to the AI agent along with email content
5. Agent analyzes images, reads documents, and responds accordingly

### Example Prompts

```
User: "Please summarize this document" (with PDF attachment)
Agent: "The document discusses... [summary based on PDF content]"

User: "What's in this image?" (with image attachment)
Agent: "The image shows... [description of image]"
```

## Troubleshooting

### Credentials not found

- Make sure you set `AK_GMAIL__CLIENT_ID` and `AK_GMAIL__CLIENT_SECRET` environment variables

### OAuth2 flow failed

- Add your email as test user in OAuth consent screen
- Enable Gmail API in Google Cloud
- Delete `token.pickle` and retry
- Make sure your environment variables are set correctly (client ID, secret, etc.)

### No agent available

- Check `AK_GMAIL__AGENT` matches agent name
- Verify OpenAI API key

### Access blocked: Authorization Error

- App needs verification for external users
- Add Gmail addresses as test users

### Rate limit exceeded

- Gmail API has quota limits
- Increase `poll_interval`

## API Rate Limits

- Gmail API: 250 queries/user/day (default)
- Sending: 100 emails/day (test users)

## Gmail vs Messenger/Telegram Comparison

| Feature      | Gmail            | Messenger/Telegram  |
| ------------ | ---------------- | ------------------- |
| Message Type | Email (threaded) | Chat/message        |
| Auth         | OAuth2           | Token/secret        |
| Real-time    | Polling (30s+)   | Webhook (instant)   |
| Attachments  | Yes              | Yes (basic)         |
| App Review   | Not required     | Messenger: required |
| Quota        | 250 queries/day  | Higher              |

## Example Projects

- Basic Example: `examples/api/gmail/server.py`

## References

- [Gmail API Documentation](https://developers.google.com/gmail/api)
- [OAuth2 for Desktop Apps](https://developers.google.com/identity/protocols/oauth2#installed)