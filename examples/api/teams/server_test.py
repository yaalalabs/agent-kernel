"""
Test script for Teams integration
This script tests the Teams bot locally without requiring a full Teams setup.
"""

import asyncio
import logging

from agentkernel.core import Config
from agentkernel.openai import OpenAIModule
from agentkernel.teams import AgentTeamsRequestHandler
from agents import Agent as OpenAIAgent
from botbuilder.schema import (
    Activity,
    ActivityTypes,
    ChannelAccount,
    ConversationAccount,
)

# Configure logging
logging.basicConfig(level=logging.DEBUG)

# Create agent
general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and clear answers",
)

OpenAIModule([general_agent])


async def test_teams_handler():
    """Test the Teams handler with a mock message."""
    # Initialize handler
    handler = AgentTeamsRequestHandler()

    # Create a mock activity (Teams message)
    mock_activity = Activity(
        type=ActivityTypes.message,
        id="test-activity-id",
        text="Hello, what is the capital of France?",
        from_property=ChannelAccount(id="user-123", name="Test User"),
        conversation=ConversationAccount(id="test-conversation-123"),
        channel_id="msteams",
    )

    # Create a mock TurnContext
    # Note: This is a simplified test. For full testing, you'd need to mock the adapter and credentials
    print("Testing Teams handler...")
    print(f"Mock message: {mock_activity.text}")
    print(f"From: {mock_activity.from_property.name}")
    print(
        "\nNote: Full integration test requires Azure Bot credentials and Teams environment."
    )
    print("Use 'uv run server.py' with proper credentials for real testing.")


if __name__ == "__main__":
    asyncio.run(test_teams_handler())
