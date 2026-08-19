# Microsoft Teams Integration

Microsoft Teams integration for Agent Kernel using Azure Bot Framework.

The `AgentTeamsRequestHandler` class handles conversations with agents via Microsoft Teams. This integration uses the Azure Bot Framework to receive messages and send responses, supporting text, images, and file attachments.

## How It Works

1.  When a message is sent to the bot in Teams, Azure Bot Service sends a payload to your configured **Webhook URL**.
2.  The handler verifies the request and authenticates it using your Azure App credentials.
3.  The message is processed and passed to your chosen Agent.
4.  The Agent's response is sent back to Teams using the Bot Framework APIs. The agent runs
    *outside* the webhook turn (a proactive `continue_conversation` follow-up), so a slow agent
    cannot exceed the Bot Framework delivery timeout and cause Azure to redeliver the activity.
5.  File attachments are automatically downloaded (handling authentication) and passed to the agent. Audio and video are rejected, and anything over `api.max_file_size` is refused.

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

Most files Teams delivers carry a **pre-authenticated `downloadUrl`**, which the handler fetches with
no extra credentials. That is the common path and it requires no Azure permissions at all.

When a download URL is *not* pre-authenticated, the handler falls back to an app-only (client
credentials) token minted for the host serving the file. That fallback needs:

*   **A tenant ID.** The client credentials grant is not valid against the `/common` authority, so a
    specific tenant is required. The handler prefers the tenant on the incoming activity and uses
    `AK_TEAMS__TENANT_ID` as the fallback; if neither is available the download is refused with a
    clear message rather than retried unauthenticated.
*   **A SharePoint application permission** — `Sites.Read.All` under *Office 365 SharePoint Online*
    (not Microsoft Graph), with admin consent — because the token requested is for the SharePoint
    resource serving the file:
    *   Go to **API permissions** > **Add a permission** > **APIs my organization uses** >
        **Office 365 SharePoint Online** > **Application permissions** > `Sites.Read.All`.
    *   **Grant admin consent** for your organization.

A bearer token is only ever sent to a host it was minted for. An unrecognised download host is
fetched without an `Authorization` header rather than being handed a token.

## Troubleshooting

*   **Bot doesn't respond**: Check your webhook URL in Azure Bot Configuration. Ensure it handles POST requests to `/teams/messages`.
*   **401 Unauthorized downloading files**:
    *   The integration automatically handles pre-authenticated (`tempauth`) URLs provided by Teams.
    *   `Cannot authorize the download of ...` in the logs means the app-only fallback was needed and
        could not be used — set `AK_TEAMS__TENANT_ID` and grant the SharePoint permission above.
    *   `Direct download failed with status 401` means the URL itself was rejected — confirm the bot
        still has access to the file and that the `downloadUrl` has not expired.
*   **Duplicate replies**: the agent runs outside the webhook turn, so this normally means more than
    one instance is registered on the same messaging endpoint.
*   **"Operation returned an invalid status code 'Unauthorized'"**: Check that your `AK_TEAMS__APP_ID` and `AK_TEAMS__APP_PASSWORD` are correct and match the Azure Bot resource.
