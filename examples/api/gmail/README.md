# Gmail Agent Kernel Example

AI-powered Gmail bot that automatically reads and replies to emails using Agent Kernel and OpenAI.

## Prerequisites

1. **Google Cloud Project** with Gmail API enabled
2. **OAuth2 Credentials** (client ID and secret from Google Cloud)
3. **OpenAI API Key**

## Setup

### 1. Create Google Cloud Project & Enable Gmail API

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select existing)
3. Enable Gmail API:
   - Go to **APIs & Services** → **Library**
   - Search for "Gmail API"
   - Click **Enable**

### 2. Create OAuth2 Credentials

1. Go to **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **OAuth client ID**
3. If prompted, configure OAuth consent screen:
   - User Type: **External** (for testing)
   - App name: Your app name
   - User support email: Your email
   - Developer contact: Your email
   - Scopes: Add `gmail.readonly`, `gmail.send`, `gmail.modify`
   - Test users: Add your Gmail address
4. Back to Create OAuth client ID:
   - Application type: **Desktop app**
   - Name: "Gmail Agent Kernel"
   - Click **Create**
5. Copy the `client_id` and `client_secret` from the credentials JSON file (no need to save the file)

### 3. Configure Environment Variables (No credentials.json needed)

```bash
# OAuth2 Credentials (REQUIRED)
export AK_GMAIL__CLIENT_ID="your-google-client-id"
export AK_GMAIL__CLIENT_SECRET="your-google-client-secret"

# OpenAI Configuration (REQUIRED)
export OPENAI_API_KEY="your_openai_api_key"

# Gmail Configuration (Optional)
export AK_GMAIL__REDIRECT_URIS="http://localhost"  # Default: http://localhost
export AK_GMAIL__AGENT="general"                   # Agent to handle emails (default: general)
export AK_GMAIL__TOKEN_FILE="token.pickle"        # OAuth token storage (default: token.pickle)
export AK_GMAIL__POLL_INTERVAL="30"               # Polling interval in seconds (default: 30)
export AK_GMAIL__LABEL_FILTER="INBOX"             # Gmail label to monitor (default: INBOX)

# Email Signature Customization 
export AK_CLIENT_NAME="Your Name"                 # Name for email signatures
export AK_GMAIL_SIGN_OFF="Best regards"           # Sign-off format (e.g., "Sincerely", "Kind regards")

# Email Filtering 
export AK_GMAIL__SENDER_FILTER="user@example.com,support@company.com"  # Only from these senders
export AK_GMAIL__SUBJECT_FILTER="Support,Help,Urgent"                   # Only with these keywords
```

**Note:** You do NOT need to provide a credentials.json file. The handler will use these environment variables directly for authentication.

## Build

Install dependencies using:

```bash
./build.sh
```

For local development with Agent Kernel source:

```bash
./build.sh local
```

## Run

Start the Gmail bot:

```bash
uv run server.py
```

### First Run - OAuth Authentication

On first run, the bot will:

1. Open your browser automatically
2. Ask you to sign in to Google
3. Request permissions for Gmail access
4. Save credentials to `token.pickle`

**Important**: Make sure you're signed in with the Gmail account you added as a test user in the OAuth consent screen.

### Subsequent Runs

The bot will use the saved `token.pickle` and start polling immediately.

## How It Works

1. **Polling Loop**: Bot checks for unread emails every 30 seconds (configurable)
2. **Email Detection**: Finds unread emails in INBOX (or specified label)
3. **Thread Context**: Fetches thread history (last 5 messages) for conversation context
4. **Attachment Extraction**: Extracts images and files from email attachments
5. **AI Processing**: Sends email content + thread history + attachments to OpenAI agent
6. **Reply Generation**: Agent generates response with full conversation awareness
7. **Send Reply**: Sends AI response as email reply (maintains Gmail thread)
8. **Signature**: Automatically adds configured signature (name + sign-off)
9. **Mark Read**: Marks original email as read

## Image & File Attachments

The Gmail integration supports processing email attachments and passing them to your AI agent for analysis.

### Supported File Types

**Images:**

- JPEG (.jpg, .jpeg)
- PNG (.png)
- GIF (.gif)
- WebP (.webp)

**Documents:**

- PDF (.pdf)
- Microsoft Word (.doc, .docx)
- Microsoft Excel (.xls, .xlsx)

### How Attachments Work

1. Attachments are automatically extracted from incoming emails
2. MIME types are detected (or inferred from file extension)
3. Files are converted to base64 and passed to the AI agent
4. Agent can analyze images, read documents, and answer questions about attachments

### Example Use Cases

- "Please summarize this PDF" (with PDF attachment)
- "What's in this image?" (with image attachment)
- "Extract the data from this spreadsheet" (with Excel attachment)

## Email Threading

Each Gmail thread is treated as a separate conversation:

- **Thread Isolation**: Different threads maintain independent agent sessions
- **Context Awareness**: Agent sees full conversation history within a thread
- **Proper Threading**: Replies use `In-Reply-To` and `References` headers for Gmail threading
- **One Response Per Thread**: Each new user message in a thread gets one AI response

### Example

```
Thread: "Question about pricing"
├── User: "What's your pricing?"
│   └── Agent: "We offer 3 tiers..." [includes signature]
├── User: "What about discounts?"
│   └── Agent: "Yes, we offer bulk discounts..." [includes signature]
└── User: "Can I get a quote?"
    └── Agent: "Sure, I'll prepare a quote..." [includes signature]
```

## Configuration

Edit `config.yaml`:

```yaml
gmail:
  agent: general                        # Agent to use for email processing
  token_file: "token.pickle"            # Token storage location
  poll_interval: 30                     # Polling interval in seconds
  label_filter: "INBOX"                 # Gmail label to monitor
```

### Agent Customization

Edit the agent instructions in `server.py`:

```python
general_agent = OpenAIAgent(
    name="general",
    instructions="""Your custom instructions here..."""
)
```

## Example Email Flow

**Incoming Email:**

```
From: user@example.com
Subject: Question about pricing
Body: Hi, what are your pricing options?
```

**AI Response:**

```
Subject: Re: Question about pricing
Body: Thank you for your inquiry! We offer several pricing tiers:
...
```

## Filtering Emails

### Monitor Specific Label

```yaml
gmail:
  label_filter: "my-custom-label"
```

### Monitor Multiple Labels

The handler currently supports one label. To monitor multiple, you can:

1. Create Gmail filter that applies a common label
2. Or modify the code to query multiple labels

## Troubleshooting

### Credentials not found

- Make sure you set `AK_GMAIL__CLIENT_ID` and `AK_GMAIL__CLIENT_SECRET` environment variables

### OAuth2 flow failed

- Ensure you added your email as a test user in OAuth consent screen
- Check if Gmail API is enabled in your Google Cloud project
- Try deleting `token.pickle` and re-authenticating
- Make sure your environment variables are set correctly (client ID, secret, etc.)

### No agent available

- Check that `AK_GMAIL__AGENT` matches the agent name in `server.py`
- Verify OpenAI API key is set: `echo $OPENAI_API_KEY`

### Access blocked: Authorization Error

- Your app needs to be verified if using external users
- For testing, add specific Gmail addresses as test users
- Or set OAuth consent screen to Internal (if using Google Workspace)

### Rate limit exceeded

- Gmail API has quota limits
- Increase `poll_interval` to reduce API calls
- Check quota usage in Google Cloud Console

## Advanced Usage

### Custom Email Query

The agent uses a Gmail search query string to filter which messages it processes. Here are some example queries you can use when configuring or extending the agent:

```python
# Example: Only emails from specific sender
query = "is:unread from:important@example.com"

# Example: Emails with specific subject
query = "is:unread subject:urgent"

# Example: Combine multiple criteria
query = "is:unread label:inbox -from:noreply"
```

## Gmail API Scopes

This integration uses:

- `https://www.googleapis.com/auth/gmail.readonly` - Read emails
- `https://www.googleapis.com/auth/gmail.send` - Send emails
- `https://www.googleapis.com/auth/gmail.modify` - Mark as read, apply labels

## Resources

- [Gmail API Documentation](https://developers.google.com/gmail/api)
- [OAuth2 for Desktop Apps](https://developers.google.com/identity/protocols/oauth2#installed)
- [Agent Kernel Documentation](https://github.com/yaalalabs/agent-kernel)