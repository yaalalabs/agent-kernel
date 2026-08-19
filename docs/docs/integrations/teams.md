---
sidebar_position: 6
---

# Microsoft Teams

Agent Kernel supports integration with Microsoft Teams via the Azure Bot Framework. This allows you to deploy agents that can communicate in 1:1 chats, group chats, and Teams channels, supporting text, images, and file attachments.

## How It Works

1.  **Azure Bot Service**: Acts as the bridge between the Teams client and your Agent Kernel server.
2.  **Webhook**: Your Agent Kernel server exposes a `/teams/messages` endpoint that receives activities from Azure.
3.  **Agent Processing**: Incoming messages are routed to your configured Agent.
4.  **Response**: The Agent's reply is sent back to the conversation via the Bot Framework Connector.

## Setup Guide

Setting up a Teams bot involves three main parts: Azure, your Agent Kernel Server, and the Teams Developer Portal.

### 1. Azure App Registration

1.  Log in to the **[Azure Portal](https://portal.azure.com)**.
2.  Go to **App registrations** > **New registration**.
3.  **Name**: Enter your bot's name (e.g., "Agent Bot").
4.  **Supported account types**: Select **"Accounts in any organizational directory (Any Microsoft Entra ID tenant - Multitenant)"**.
5.  Click **Register**.
6.  **Copy the Application (client) ID**. You'll use this as `AK_TEAMS__APP_ID`.
7.  Go to **Certificates & secrets** > **New client secret**. Create one and **copy the Value**. You'll use this as `AK_TEAMS__APP_PASSWORD`.

### 2. Create Azure Bot Resource

1.  Search for **Azure Bot** in the Azure Portal and click **Create**.
2.  **Handle**: Pick a unique handle.
3.  **Type of App**: Select **Multi Tenant**.
4.  **Creation type**: **Use existing app registration**. Paste the App ID from Step 1.
5.  Click **Review + create**.

### 3. Configure Webhook

1.  In your new Azure Bot resource, go to **Configuration**.
2.  **Messaging endpoint**: Enter your server's public URL + `/teams/messages`.
    *   Example: `https://your-server.com/teams/messages`
3.  Click **Apply**.
4.  Go to **Channels** and add **Microsoft Teams**. accepting the terms.

### 4. Teams Developer Portal

1.  Open the **Developer Portal** app inside Microsoft Teams.
2.  Create a **New app**.
3.  In **App features**, select **Bot**.
4.  **Select an existing bot** and paste your **Client ID** (from Step 1).
5.  Select scopes (Personal, Team, Group Chat) and Save.
6.  Go to **Publish to org** to submit for admin approval, or **Preview in Teams** to test immediately.

## Configuration

Pick the agent in `config.yaml`:

```yaml
teams:
  agent: "general"                                    # Default agent for Teams messages
  agent_acknowledgement: "I'm looking into that..."   # Optional: sent as soon as a message arrives
  tenant_id: ""                                       # Optional: see "Attachment downloads" below
```

Supply the bot credentials as environment variables, so secrets stay out of the config file:

```bash
# Required
export AK_TEAMS__APP_ID="your-azure-client-id"
export AK_TEAMS__APP_PASSWORD="your-azure-client-secret"

# Optional
export AK_TEAMS__TENANT_ID="your-tenant-id"
```

Every key is settable either way: `teams.agent` is also `AK_TEAMS__AGENT`, and so on.

## Features

*   **Text Messaging**: Full support for 1:1, group chat, and channel conversations.
*   **File Attachments**: Uploaded files are downloaded and passed to the agent. Audio and video are
    rejected, and anything over `api.max_file_size` is refused while streaming rather than buffered.
*   **Images**: Images pasted or dragged into the chat are fetched from the Bot Connector using the
    bot's own credentials and passed to the agent.
*   **Mentions**: The bot's own `@BotName` mention is stripped from the prompt. Mentions of other
    people keep their display name, and text that merely looks like a handle — an email address, a
    `@decorator` — is left untouched.
*   **Long replies**: Replies larger than a single Teams message are split across several messages.

### Attachment downloads

Most files Teams delivers carry a pre-authenticated `downloadUrl`, which the handler fetches with no
extra credentials — that is the common path and it needs no Azure permissions at all.

When a download URL is *not* pre-authenticated, the handler falls back to an app-only
(client credentials) token for the host serving the file. That fallback needs:

*   **`teams.tenant_id` set.** The client credentials grant is not valid against the `/common`
    authority, so a specific tenant is required. The handler prefers the tenant on the incoming
    activity and uses `teams.tenant_id` as the fallback; if neither is available the download is
    refused with a clear message rather than being retried unauthenticated.
*   **A SharePoint application permission** — `Sites.Read.All` under *Office 365 SharePoint Online*,
    with admin consent — because the token requested is for the SharePoint resource serving the file,
    not for Microsoft Graph.

A bearer token is only ever sent to a host it was minted for. An unrecognised download host is
fetched without an `Authorization` header rather than being handed a token.

## Troubleshooting

### 401 Unauthorized Downloads
If the bot fails to download files:
*   Check the logs for `Cannot authorize the download of ...`. That means the app-only fallback was
    needed and could not be used — set `teams.tenant_id` and grant the SharePoint permission above.
*   `Direct download failed with status 401` means the URL itself was rejected. Confirm the bot still
    has access to the file and that the `downloadUrl` has not expired.

### Bot Not Responding
*   Check Azure Bot **Configuration** to ensure the **Messaging endpoint** is correct and accessible.
*   Verify your App ID and Password in environment variables match the Azure App Registration. A
    credential mismatch is answered with HTTP 401, which appears in your access logs.

### Duplicate replies
The agent runs outside the webhook turn (via a proactive `continue_conversation` follow-up), so a
slow agent cannot exceed the Bot Framework delivery timeout and make Azure redeliver the activity.
If you still see duplicates, check that only one instance is registered on the messaging endpoint.
