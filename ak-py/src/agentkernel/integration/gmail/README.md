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
   - Save as `credentials.json` in your project directory

3. **Configure OAuth Consent Screen**
   - Set up the OAuth consent screen
   - Add required scopes: `gmail.readonly`, `gmail.send`, `gmail.modify`
   - Add test users if in testing mode


### Required Environment Variables (No credentials.json needed)

Set the following environment variables with your Google Cloud OAuth2 credentials:

```bash
export AK_GMAIL__CLIENT_ID="your-google-client-id"
export AK_GMAIL__CLIENT_SECRET="your-google-client-secret"
# Optional: comma-separated list of redirect URIs (default: http://localhost)
export AK_GMAIL__REDIRECT_URIS="http://localhost"
export AK_GMAIL__TOKEN_FILE="path/to/token.pickle"  # Will be created after first auth
export AK_GMAIL__POLL_INTERVAL="30"  # Seconds between checks, optional
```

**Note:** You do NOT need to provide a credentials.json file. The handler will use these environment variables directly for authentication.

### OAuth Flow

On first run, the handler will:
1. Open a browser for Google OAuth consent
2. Request permissions to read/send emails
3. Save the token for future use

## Simple Gmail Integration Code

```python
from agents import Agent as OpenAIAgent
from agentkernel.openai import OpenAIModule
from agentkernel.gmail import AgentGmailHandler
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
    handler = AgentGmailHandler()
    asyncio.run(handler.start_polling())
```

## Configuration Options


### config.yaml

```yaml
gmail:
    agent: "general"  # Name of the agent to handle emails
    poll_interval: 30  # Seconds between polling for new emails
    # credentials_file: "credentials.json"  # No longer needed
    token_file: "token.pickle"  # Path to store OAuth token
```

**Do not keep secrets or keys in the config file. Set them as environment variables as shown above.**

## Features

### Supported Email Features

- **Plain Text Emails**: Standard text email content
- **HTML Emails**: HTML content is converted to plain text
- **Email Threading**: Replies maintain conversation thread
- **Attachments**: Basic attachment detection (content not processed)

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

## Advanced Usage

### Custom Email Handling

You can extend the handler for custom behavior:

```python
from agentkernel.gmail import AgentGmailHandler

class CustomGmailHandler(AgentGmailHandler):
    async def _process_email(self, email: dict):
        subject = email.get("subject", "")
        
        # Custom logic here
        if "[AUTO-REPLY]" in subject:
            return  # Skip auto-replies
        
        # Call parent handler
        await super()._process_email(email)
```

### Filtering Emails

You can customize which emails to process:

```python
# Only process emails from specific senders
allowed_senders = ["user@example.com"]

# Only process emails with specific subjects
subject_filters = ["Support Request", "Help Needed"]
```

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

