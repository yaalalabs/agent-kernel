# Slack integration 
This example shows how to create a local server based slack integration
You need to setup the required Slack Apps and obtain the necessary slack key and tokens. Please follow the instructions in https://api.slack.com/apps/
Please enable subscription to **app_mention** event for the Bot.

The agent in this example has one tool, `restart_service`, that cannot run until a human approves
it. Ask the bot to restart something and it replies with a paused message carrying **Approve** and
**Deny** buttons; the tool runs only when Approve is pressed, and Deny opens a short form asking
why, which the agent is told.

**Those buttons need one more switch in the Slack app.** Presses are delivered to
*Interactivity & Shortcuts*, which is off by default and separate from Event Subscriptions. Turn it
on and set its Request URL to the **same** URL as your event subscription — `/slack/events` serves
both. Skip this and the pause still renders, the buttons still appear, and pressing one does
nothing.

Anyone who can see the message can press the buttons. Agent Kernel ships no approver policy; see
[Human in the Loop](../../../docs/docs/advanced/human-in-the-loop.md) for enforcing one.

## Setup
Please refer to the [SlackInboundAdapter](../../../ak-py/src/agentkernel/integration/slack/README.md) for setting up the Slack

## Build

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

# Run
Run this demo using the following.

You will need to setup the following env variables

```
export SLACK_SIGNING_SECRET="your secret"
export SLACK_BOT_TOKEN="your token"
export OPENAI_API_KEY=<your open ai key>

```
Run server:

    uv run server.py


## Advanced Slack integrations
You can subclass `SlackInboundAdapter` (override `_to_request`) or `SlackOutboundAdapter` and pass your instance to `WebhookRESTRequestHandler`. Please look at the `SlackInboundAdapter` class for details.