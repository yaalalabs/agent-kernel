# Slack integrations
Slack allows developers to interact with the application coversations via SlackApps (https://api.slack.com/apps/)

The class AgentSlackRequestHandler handles simple conversations with Agents of your choice in API deployment. This class does the following

1. When a message is recived from slack addressed to the bot it will first acknowledge with a prompot and processing emoji 
2. The question is extracted and passed to the Agent of your choice
3. Once the Agent response is ready, the previously posted message is modified
4. The response is posted to the thread.

You can implement a more feature rich integration  based on the AgentSlackRequestHandler class.


## Simple integration code

```
from agents import Agent as OpenAIAgent
from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agentkernel.integrations.slack import AgentSlackRequestHandler

general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and clear answers",
)

OpenAIModule([general_agent])


if __name__ == "__main__":
    handler = AgentSlackRequestHandler()
    RESTAPI.run(handler=handler)
```

You need the following environment variables for the integration. 

```
export AK_SLACK_BOT_USER_ID=< >
export AK_SLACK_SIGNING_SECRET=< >
export AK_SLACK_BOT_TOKEN=< >
```

A more detailed example is provided in the examples section.