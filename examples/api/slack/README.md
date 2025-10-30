# Slack integration 
This example shows how to create a local server based slack integration
You need to setup the required Slack Apps and obtain the necessary slack key and tokens. Please follow the instructions in https://api.slack.com/apps/
Please enable subscription to **app_mention** event for the Bot.

## Setup
You need the following environment variables for the integration. Or you can setup the config.yaml provided in this folder

```
export AK_SLACK_BOT_USER_ID=< >
export AK_SLACK_SIGNING_SECRET=< >
export AK_SLACK_BOT_TOKEN=< >
```

You can use https://pinggy.io/ for local testing. See this article https://pinggy.io/blog/how_to_get_slack_webhook/


## Build

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

# Run
Run this demo using the following.

Run server:

    uv run server.py


## Advanced Slack integrations
You can write your own Handler and pass it to RESTAPI.run() method. Please look at the AgentSlackRequestHandler class for details.