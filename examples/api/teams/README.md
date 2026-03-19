# Microsoft Teams Bot Example

This example demonstrates how to run a Microsoft Teams bot using Agent Kernel.

## Prerequisites

1.  **Azure Account**: Access to create App Registrations and Bot Services.
2.  **Microsoft Teams**: Access to Developer Portal in Teams.
3.  **Tunneling Tool**: `ngrok` or similar for local development (Teams requires a public HTTPS URL).

## Setup

### 1. Configure Credentials

Follow the detailed **[Setup Guide](../../../ak-py/src/agentkernel/integration/teams/README.md)** to register your bot in Azure and Teams.

You will need:
*   **App ID** (from Azure App Registration)
*   **App Password** (Client Secret from Azure)

### 2. Configure Environment Variables

Create a `.env` file or export the following variables:

```bash
# Teams Bot Credentials
export AK_TEAMS__APP_ID="your-azure-client-id"
export AK_TEAMS__APP_PASSWORD="your-azure-client-secret"

# Optional: Tenant ID (if single tenant, otherwise defaults to "common")
# export AK_TEAMS__TENANT_ID="your-tenant-id"

# OpenAI API Key for the agent
export OPENAI_API_KEY="sk-..."
```

### 3. Create Configuration File

Create `config.yaml` to define your agent:

```yaml
teams:
  agent: "general"
  agent_acknowledgement: "I'm looking into that for you..." # Optional
```

## Build and Run

1.  **Install Dependencies**:
    ```bash
    ./build.sh
    ```

2.  **Start the Server**:
    ```bash
    uv run server.py
    ```
    The server listens on `http://0.0.0.0:8000`.

## Expose Local Server

For Teams to communicate with your local bot, you must expose port 8000 to the internet.

**Using ngrok:**
```bash
ngrok http 8000
```

Copy the HTTPS URL (e.g., `https://1234abcd.ngrok-free.app`) and update your **Azure Bot Messaging Endpoint** to:
`https://1234abcd.ngrok-free.app/teams/messages`

## Testing

1.  Go to Microsoft Teams.
2.  Select your Bot (preview/sideloaded via Developer Portal).
3.  Send a message: "Hello".
4.  The bot should reply using the configured Agent.
5.  **File Testing**: Drag and drop a file (like a PDF) into the chat. The bot should download and process it.

## Troubleshooting

See the [Integration README](../../../ak-py/src/agentkernel/integration/teams/README.md#troubleshooting) for common issues.
