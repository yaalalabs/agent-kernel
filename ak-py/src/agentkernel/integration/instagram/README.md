# Instagram Business API Integration

Instagram Business Messaging integration for Agent Kernel using **Instagram API with Business Login for Instagram** (without Facebook Login).

The `AgentInstagramRequestHandler` class handles conversations with agents via Instagram Messaging API webhooks. This integration uses the Instagram Graph API (`graph.instagram.com`) directly, allowing Professional accounts to connect without requiring a Facebook Page.

## How It Works

1. When a message is received from Instagram DM, it's verified and authenticated
2. A typing indicator is displayed to show the bot is processing
3. The message is extracted and passed to your chosen Agent
4. The Agent response is sent back as an Instagram message
5. Long messages are automatically split to respect Instagram's character limits (1000 chars)

## API Endpoint

This integration uses the Instagram Graph API directly:

```
POST https://graph.instagram.com/{api_version}/me/messages
```

This requires an **Instagram User Access Token** (starts with `IGAA...`).

## Instagram Business Login Setup

### Prerequisites

- A [Meta Developer account](https://developers.facebook.com/)
- A Meta App with Instagram API product enabled
- An Instagram Professional account (Business or Creator)

### Configuration Steps

1. **Create a Meta App**
   - Go to https://developers.facebook.com/apps
   - Create a new app and select "Business" type
   - Add **Instagram API** product (with Business Login)

2. **Set Up Business Login for Instagram**
   - In **Use Cases**, select "Instagram Business"
   - Click "API setup with Instagram login"
   - Add required permissions:
     - `instagram_business_basic`
     - `instagram_business_manage_messages`

3. **Generate Access Token**
   - Go to "Generate access tokens" section
   - Add your Instagram Professional account
   - Generate a token with the required permissions
   - The token will start with `IGAA...`

4. **Get Your Credentials**
   - **Access Token**: Generated from the step above (starts with `IGAA...`)
   - **App Secret**: App > App Settings > Basic (for webhook signature verification)
   - **Verify Token**: Create your own secure random string for webhook verification

5. **Configure Webhook**
   - In "Configure webhooks" section, enter:
     - **Callback URL**: Your public HTTPS endpoint + `/instagram/webhook`
     - **Verify Token**: Your chosen verify token
   - Subscribe to `messages` field

## Environment Variables

```bash
# Required
export AK_INSTAGRAM__VERIFY_TOKEN="your_secure_verify_token"
export AK_INSTAGRAM__ACCESS_TOKEN="IGAA..."  # Instagram User Access Token

# Optional
export AK_INSTAGRAM__APP_SECRET="your_app_secret"  # For webhook signature verification
export AK_INSTAGRAM__API_VERSION="v21.0"  # Default is v21.0

# OpenAI API Key for the agent
export OPENAI_API_KEY="your_openai_api_key"
```

## Configuration File (config.yaml)

```yaml
instagram:
  agent: "general"
  api_version: "v21.0"
```

## Basic Usage

```python
from agentkernel.api import RESTAPI
from agentkernel.instagram import AgentInstagramRequestHandler
from agentkernel.openai import OpenAIModule
from agents import Agent as OpenAIAgent

# Create your agent
agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance via Instagram DM."
)

# Initialize module
OpenAIModule([agent])

# Start server
handler = AgentInstagramRequestHandler()
RESTAPI.run([handler])
```

## Webhook Events Handled

- `messages`: Text messages from users
- `messaging_postbacks`: Button clicks and quick replies
- `messaging_reads`: Read receipts (logged only)
- `messaging_reactions`: Message reactions (logged only)

## Character Limits

Instagram DM messages have a 1000 character limit. Long responses are automatically split into multiple messages.

## Troubleshooting

### 401 Unauthorized / Cannot Parse Access Token

This is the most common issue. It occurs when:
- Using a Facebook Page Access Token instead of Instagram User Access Token
- Token has expired (tokens are valid for 60 days)
- Token doesn't have required permissions

**Solution**: Generate a new token from Business Login for Instagram (should start with `IGAA...`)

### Webhook Verification Fails

- Ensure verify token matches exactly
- Check that endpoint returns plain integer for challenge
- Verify URL is accessible via HTTPS

### Messages Not Received

- Confirm webhook subscription is active
- Check that `messages` field is subscribed
- Verify Instagram account is a Professional account

### Permission Errors

- Ensure app has `instagram_business_manage_messages` permission
- Check access token has required scopes
- Verify Instagram account is Business or Creator type

## Resources

- [Instagram API with Instagram Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login)
- [Webhook Setup Guide](https://developers.facebook.com/docs/instagram-platform/webhooks)
