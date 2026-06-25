from agentkernel.openai import OpenAIToolBuilder
from agents import Agent

from tool import get_region_memory, lookup_disposal_category, remember_region_rule

INSTRUCTIONS = """
You are a waste sorting advisor. Help users decide how to dispose of an item based on:
1. the item itself,
2. the likely or stated material,
3. the user's local recycling rules.

Always call lookup_disposal_category before giving disposal advice. If the user provides a region,
use it in the lookup. If the user gives a local rule such as "my city accepts cartons in recycling",
call remember_region_rule so future turns in that region can use it.

Keep answers practical and concise. Include the recommended category, why it applies, and one local
caution when the rule depends on the user's municipality. If material or region is missing, make a
best-effort recommendation and ask one short clarifying question.
"""

waste_sorting_agent = Agent(
    name="waste_sorting_advisor",
    handoff_description="Advises on recycling, compost, landfill, hazardous waste, and local disposal rules.",
    instructions=INSTRUCTIONS,
    tools=OpenAIToolBuilder.bind([lookup_disposal_category, remember_region_rule, get_region_memory]),
)

AGENTS = [waste_sorting_agent]
