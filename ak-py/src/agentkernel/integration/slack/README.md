# Slack integration
Slack allows developers to interact with the application conversations via SlackApps (https://api.slack.com/apps/)
It uses the Slack Events Http API (https://docs.slack.dev/apis/events-api/)

The class AgentSlackRequestHandler handles simple conversations with Agents of your choice in API deployment. This class does the following

1. When a message is received from slack addressed to the bot it will first acknowledge with a message ("agent_acknowledgement" ) and processing emoji, if it's defined in the config 
2. The question is extracted and passed to the Agent of your choice
3. Once the Agent response is ready, the previously posted message is modified
4. The response is posted to the thread.

You can implement a more feature rich integration  based on the AgentSlackRequestHandler class.

## Slack setup
You need to setup Slack app and obtain signing-secret & a bot user token. Also enable subscription to the following events.
1. message.im
2. message.channels
2. app_mention

When you subscribe to events some OAuth scopes are automatically added. In addition to that these minimum scopes needs to be added for the bot to function
1. chat:write
2. im:write

You need to set the following environment variables for the integration. 

```
export SLACK_SIGNING_SECRET=< >
export SLACK_BOT_TOKEN=< >
```

The AgentSlackRequestHandler listens on /slack/events, hence you need to setup the webhook URL as https://<your domain or IP>:<port>/slack/events
During URL registration, Slack sends a challenge to the URL before enabling. The AgentSlackRequestHandler handles this, hence you don't need any separate code to activate.

You can use https://pinggy.io/ or similar for local testing (e.g. ssh -p 443 -R0:localhost:8000 a.pinggy.io). [How to use pinggy to test Slack](https://pinggy.io/blog/how_to_get_slack_webhook/)

A detailed example is provided in the examples section.


## Simple Slack integration code

```
from agents import Agent as OpenAIAgent
from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agentkernel.slack import AgentSlackRequestHandler

general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and clear answers",
)

OpenAIModule([general_agent])


if __name__ == "__main__":
    handler = AgentSlackRequestHandler()
    RESTAPI.run([ AgentSlackRequestHandler()]) # Note: you can pass multiple handlers to support multiple integrations
```

