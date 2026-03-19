# Instagram Business API Integration Example

This example demonstrates how to create an Instagram Business Messaging integration with Agent Kernel using **Instagram API with Business Login for Instagram** (without Facebook Login).

## Overview

This integration uses the Instagram Graph API (`graph.instagram.com`) directly, which allows Instagram Professional accounts (Business or Creator) to connect without requiring a Facebook Page.

## Prerequisites

1. Meta Developer Account
2. Meta App with Instagram API product added
3. Instagram Business or Creator account
4. Business Login for Instagram configured (no Facebook Page required)
5. Webhook configured in Meta Developer Portal
6. Required credentials (see below)

## Setup

### 1. Get Instagram API Credentials

Follow the setup guide in [AgentInstagramRequestHandler](../../../ak-py/src/agentkernel/integration/instagram/README.md)

You'll need:

- Access Token (from Business Login - starts with `IGAA...`)
- App Secret (optional but recommended for webhook signature verification)
- Verify Token (you create this - any secure random string)

### 2. Configure Environment Variables

Create a `.env` file or export these variables:

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

### 3. Create Configuration File

Create `config.yaml`:

```yaml
instagram:
  agent: "general"
  api_version: "v21.0"
```

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

Start the server:

```bash
uv run server.py
```

The server will start on `http://localhost:8000` by default.

## Expose Local Server

For local testing, expose your server using a tunnel:

### Using ngrok:

```bash
ngrok http 8000
```

### Using pinggy:

```bash
ssh -p443 -R0:localhost:8000 a.pinggy.io
```

Copy the HTTPS URL and configure it in your Instagram webhook settings.

## Configure Instagram Webhook

1. Go to https://developers.facebook.com/apps
2. Select your app
3. Go to **Instagram API** > **Use Cases** > **Customize**
4. In the "Configure webhooks" section:
   - **Callback URL**: `https://your-tunnel-url.com/instagram/webhook`
   - **Verify Token**: Same as `AK_INSTAGRAM__VERIFY_TOKEN`
5. Subscribe to `messages` webhook field
6. Enable webhook subscription toggle

## Testing

1. Open Instagram app and go to your Business account's DMs
2. Have another account (or test account) send a DM
3. The bot should display a typing indicator
4. After processing, you'll receive the agent's response
5. Check server logs to see the request/response flow

### Test Message Examples

**Text Messages:**

```bash
Hello
What services do you offer?
Can you help me with a question?
Tell me more about yourself
```

**Multimodal Messages (with attachments):**

```bash
"What's in this photo?" [attach image]
"Can you analyze this document?" [attach PDF]
"Extract text from this image" [attach screenshot]
```

### Detailed Multimodal Testing

To test multimodal features using `curl` (simulating webhook events):

**1. Image Attachment:**
```bash
curl -X POST "http://localhost:8000/instagram/webhook" \
     -H "Content-Type: application/json" \
     -d '{
  "object": "instagram",
  "entry": [{
    "id": "123456789",
    "time": 1709234567890,
    "messaging": [{
      "sender": {"id": "user_123"},
      "recipient": {"id": "page_123"},
      "timestamp": 1709234567890,
      "message": {
        "mid": "m_123456789",
        "attachments": [{
          "type": "image",
          "payload": {
            "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/d/dd/Gfp-wisconsin-madison-the-nature-boardwalk.jpg/2560px-Gfp-wisconsin-madison-the-nature-boardwalk.jpg"
          }
        }]
      }
    }]
  }]
}'
```

**2. File Attachment (PDF):**
```bash
curl -X POST "http://localhost:8000/instagram/webhook" \
     -H "Content-Type: application/json" \
     -d '{
  "object": "instagram",
  "entry": [{
    "id": "123456789",
    "time": 1709234567890,
    "messaging": [{
      "sender": {"id": "user_123"},
      "recipient": {"id": "page_123"},
      "timestamp": 1709234567890,
      "message": {
        "mid": "m_123456789",
        "attachments": [{
          "type": "file",
          "payload": {
            "url": "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
          }
        }]
      }
    }]
  }]
}'
```

## Multimodal Features

The integration now supports file and image analysis:

**Supported Attachments:**

- Images (JPEG, PNG, GIF, WebP)
- Documents (PDF, Word, Excel, PowerPoint)
- Audio and video files

**File Size Limits:**

- Default: 2 MB per file (configurable)
- Base64 encoding adds ~33% overhead
- Check logs for size validation messages

**Configuration:**

```yaml
api:
  max_file_size: 2097152  # 2 MB in bytes
```

## API Endpoint

This integration uses the Instagram Graph API directly:

```
POST https://graph.instagram.com/v21.0/me/messages
```

This is different from the Facebook Graph API approach and works with Instagram User Access Tokens (IGAA...).

## Troubleshooting

### Webhook Verification Fails

- Ensure verify token matches in both config and Meta portal
- Check that your endpoint returns 200 status with the challenge integer
- Verify URL is accessible via HTTPS

### No Messages Received

- Check webhook subscription is active (toggle is on)
- Verify Instagram account is a Professional account (Business or Creator)
- Ensure app has `instagram_business_manage_messages` permission
- Check server logs for errors

### 401 Unauthorized / Cannot Parse Access Token

- Ensure you're using an **Instagram User Access Token** (starts with `IGAA...`)
- Do NOT use a Facebook Page Access Token (starts with `EAAG...`)
- Verify token has required permissions using [Meta Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/)

### Agent Not Responding

- Verify OpenAI API key is set correctly
- Check agent configuration in config.yaml
- Review server logs for agent errors

### Permission Errors (Error 10)

- Ensure all required permissions are granted:
  - `instagram_business_basic`
  - `instagram_business_manage_messages`
- Re-generate access token with all permissions

## Production Deployment

For production deployment:

1. **Use HTTPS**: Deploy behind nginx or similar with SSL
2. **Environment Variables**: Use secure secret management
3. **Monitoring**: Add logging and alerting
4. **Scaling**: Use containerization and orchestration
5. **Error Handling**: Implement robust error handling and retries
6. **Long-lived Tokens**: Refresh tokens before they expire (60 days)

See deployment documentation for AWS and other platforms.

## Resources

- [Instagram API with Instagram Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login)
- [Webhook Setup Guide](https://developers.facebook.com/docs/instagram-platform/webhooks)
- [Agent Kernel Documentation](../../../docs/)
- [Instagram Integration Guide](../../../ak-py/src/agentkernel/integration/instagram/README.md)