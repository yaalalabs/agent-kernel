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

Configure your Agent Kernel instance using environment variables:

```bash
# Required
export AK_TEAMS__APP_ID="your-azure-client-id"
export AK_TEAMS__APP_PASSWORD="your-azure-client-secret"

# Optional
export AK_TEAMS__TENANT_ID="your-tenant-id"  # Defaults to 'common' for multi-tenant
```

## Features

*   **Text Messaging**: Full support for 1:1 and group conversations.
*   **File Attachments**: Automatically downloads and processes files (PDF files only) shared in chat specific logic to handle `tempauth` tokens for secure access.
*   **Images**: Supports viewing and generating images.
*   **Mentions**: Automatically strips `@BotName` mentions from the prompt.

## Troubleshooting

### 401 Unauthorized Downloads
If the bot fails to download files:
*   Ensure your bot is correctly handling the `downloadUrl` provided in the attachment payload.
*   Check if `Files.Read.All` application permission is required in Azure App Registration for your specific tenant configuration (though the default `tempauth` flow usually suffices).

### Bot Not Responding
*   Check Azure Bot **Configuration** to ensure the **Messaging endpoint** is correct and accessible.
*   Verify your App ID and Password in environment variables match the Azure App Registration.
