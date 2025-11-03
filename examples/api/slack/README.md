# Slack integration 
This example shows how to create a local server based slack integration
You need to setup the required Slack Apps and obtain the necessary slack key and tokens. Please follow the instructions in https://api.slack.com/apps/
Please enable subscription to **app_mention** event for the Bot.

## Setup
Please refer to the [AgentSlackRequestHandler](../../../ak-py/src/agentkernel/integrations/slack/README.md) for setting up the Slack

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
You can write your own Handler and pass it to RESTAPI.run() method. Please look at the AgentSlackRequestHandler class for details.