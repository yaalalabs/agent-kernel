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
🔄 Session management per thread \
📊 Label and filter support \
🎯 Customizable agent instructions

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


### 3. Configure Environment Variables (No credentials.json needed)

```bash
export AK_GMAIL__CLIENT_ID="your-google-client-id"
export AK_GMAIL__CLIENT_SECRET="your-google-client-secret"
# Optional: comma-separated list of redirect URIs (default: http://localhost)
export AK_GMAIL__REDIRECT_URIS="http://localhost"
export AK_GMAIL__AGENT="general"
export OPENAI_API_KEY="your_openai_api_key"
export AK_GMAIL__TOKEN_FILE="token.pickle"
export AK_GMAIL__POLL_INTERVAL="30"
export AK_GMAIL__LABEL_FILTER="INBOX"
```

**Note:** You do NOT need to provide a credentials.json file. The handler will use these environment variables directly for authentication.

### 4. Configuration File

Edit `config.yaml`:

```yaml
gmail:
  agent: general
    # credentials_file: "credentials.json"  # No longer needed
  token_file: "token.pickle"
  poll_interval: 30
  label_filter: "INBOX"
```

## Implementation

### Basic Setup

```python
from agents import Agent as OpenAIAgent
from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agentkernel.gmail import AgentGmailRequestHandler

general_agent = OpenAIAgent(
    name="general",
    instructions="""Your custom instructions here..."""
)

OpenAIModule([general_agent])

if __name__ == "__main__":
    handler = AgentGmailRequestHandler()
    RESTAPI.run([handler])
```

## Advanced Usage

### Custom Email Query

Edit `gmail_chat.py`:
```python
query = "is:unread from:important@example.com"
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
- Attachments (basic support)
- Label-based filtering

## Troubleshooting

### "Credentials not found"
- Make sure you set `AK_GMAIL__CLIENT_ID` and `AK_GMAIL__CLIENT_SECRET` environment variables

### "OAuth2 flow failed"
- Add your email as test user in OAuth consent screen
- Enable Gmail API in Google Cloud
- Delete `token.pickle` and retry
- Make sure your environment variables are set correctly (client ID, secret, etc.)

### "No agent available"
- Check `AK_GMAIL__AGENT` matches agent name
- Verify OpenAI API key

### "Access blocked: Authorization Error"
- App needs verification for external users
- Add Gmail addresses as test users

### "Rate limit exceeded"
- Gmail API has quota limits
- Increase `poll_interval`

## API Rate Limits

- Gmail API: 250 queries/user/day (default)
- Sending: 100 emails/day (test users)

## Production Deployment

✅ Use environment variables for secrets \
✅ Never commit credentials/token files \
✅ Monitor sent emails and API usage \
✅ Use secure secret management

## Gmail vs Messenger/Telegram Comparison

| Feature              | Gmail                | Messenger/Telegram        |
|---------------------|----------------------|---------------------------|
| Message Type        | Email (threaded)     | Chat/message              |
| Auth                | OAuth2               | Token/secret              |
| Real-time           | Polling (30s+)       | Webhook (instant)         |
| Attachments         | Yes                  | Yes (basic)               |
| App Review          | Not required         | Messenger: required       |
| Quota               | 250 queries/day      | Higher                    |

## Example Projects

- Basic Example: `examples/api/gmail/server.py`

## References

- [Gmail API Documentation](https://developers.google.com/gmail/api)
- [OAuth2 for Desktop Apps](https://developers.google.com/identity/protocols/oauth2#installed)

