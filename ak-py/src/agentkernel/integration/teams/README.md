# Microsoft Teams Integration

Microsoft Teams integration for Agent Kernel using Azure Bot Framework.

The `AgentTeamsRequestHandler` class handles conversations with agents via Microsoft Teams. This integration uses the Azure Bot Framework to receive messages and send responses, supporting text, images, and file attachments.

## How It Works

1.  When a message is sent to the bot in Teams, Azure Bot Service sends a payload to your configured **Webhook URL**.
2.  The handler verifies the request and authenticates it using your Azure App credentials.
3.  The message is processed and passed to your chosen Agent.
4.  The Agent's response is sent back to Teams using the Bot Framework APIs.
5.  File attachments (PDF files only) are automatically downloaded (handling authentication) and processed.

## Setup Guide

Follow these steps to configure your Teams Bot.

### 1. Azure App Registration

1.  Log in to the **[Azure Portal](https://portal.azure.com)**.
2.  Search for **App registrations** and click **New registration**.
3.  **Name**: Enter a name for your bot (e.g., "Agent Kernel Bot").
4.  **Supported account types**: Select **"Accounts in any organizational directory (Any Microsoft Entra ID tenant - Multitenant)"**.
5.  **Redirect URI**: Leave blank for now.
6.  Click **Register**.
7.  **Copy the Application (client) ID**. You will need this later.
8.  Go to **Certificates & secrets** > **New client secret**.
    *   Add a description and select an expiry.
    *   **Copy the Value** immediately. This is your **App Password**.

### 2. Create Azure Bot Resource

1.  In the Azure Portal, search for **Azure Bot**.
2.  Click **Create**.
3.  **Bot handle**: Enter a unique handle for your bot.
4.  **Resource group**: Select or create a new one.
5.  **Pricing tier**: Select "Standard" or "Free" (F0).
6.  **Type of App**: Select **"Multi Tenant"**.
7.  **Creation type**: Select **"Use existing app registration"**.
8.  **App ID**: Paste the **Application (client) ID** you copied in Step 1.
9.  Review and Create.

### 3. Configure Webhook Endpoint

1.  Once the Azure Bot resource is created, go to its **Configuration** blade.
2.  **Messaging endpoint**: Enter your public webhook URL.
    *   Format: `https://your-domain.com/teams/messages`
    *   *Note: For local development, use a tunnel like `ngrok` (e.g., `https://<id>.ngrok-free.app/teams/messages`).*
3.  Click **Apply** / **Save**.
4.  Go to the **Channels** blade.
5.  Click on the **Microsoft Teams** icon to add the Teams channel.
6.  Accept the terms and click **Save/Apply**.

### 4. Teams Developer Portal Setup

1.  Open Microsoft Teams and search for the **"Developer Portal"** app (or go to specific URL).
2.  Click **Apps** > **New app**.
3.  **Name**: Enter your bot's name.
4.  **App ID**: This generates a new ID for the Teams App manifest (NOT your Azure App ID yet).
5.  **Basic Information**: Fill in the required fields (Developer name, URLs, etc.).
6.  **App Features**:
    *   Click **App features** > **Bot**.
    *   **Select an existing bot**.
    *   **Bot ID**: Paste your **Application (client) ID** from Step 1.
    *   Select scopes: **"Personal"**, **"Team"**, and/or **"Group Chat"**.
    *   Click **Save**.
7.  **Domains**: Add your webhook domain (e.g., `your-domain.com` or `ngrok-free.app`) to the "Domains" section if needed for tabs/auth (usually strictly for bot messaging it's not mandatory, but good practice).

### 5. Submit and Test

1.  In the Developer Portal, go to **Publish to org**.
2.  Click **Publish your app** to submit it to your organization's app catalog (requires Admin approval) OR use **Preview in Teams** to sideload it for testing immediately.
3.  Once added, find your bot in the chat list.
4.  Send a message (e.g., "Hello").
5.  The bot should respond (ensure your local server is running!).

## Required Environment Variables

Configure these in your `.env` file or environment:

```bash
export AK_TEAMS__APP_ID="<Your-Application-Client-ID>"
export AK_TEAMS__APP_PASSWORD="<Your-Client-Secret-Value>"
export AK_TEAMS__TENANT_ID="<Optional-Tenant-ID>" # Optional: Leave empty for Multi-Tenant
```

## Security & Permissions

*   **Files.Read.All**: To allow the bot to download files shared in chat, you may need to grant API permissions in your Azure App Registration:
    *   Go to **API permissions** > **Add a permission** > **Microsoft Graph**.
    *   Select **Application permissions**.
    *   Search for `Files.Read.All` and add it.
    *   **Grant admin consent** for your organization.

## Troubleshooting

*   **Bot doesn't respond**: Check your webhook URL in Azure Bot Configuration. Ensure it handles POST requests to `/teams/messages`.
*   **401 Unauthorized downloading files**:
    *   The integration automatically handles `tempauth` URLs provided by Teams.
    *   If using the fallback Method, ensure the bot has `Files.Read.All` permission granted in Azure AD.
*   **"Operation returned an invalid status code 'Unauthorized'"**: Check that your `AK_TEAMS__APP_ID` and `AK_TEAMS__APP_PASSWORD` are correct and match the Azure Bot resource.
