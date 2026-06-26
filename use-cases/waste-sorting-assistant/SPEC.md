# Waste Sorting Assistant Specification

## Agent Description

A single-agent solution that advises users on the correct disposal method for a given item based on its material and the user's local recycling rules. The agent uses a tool to look up disposal categories and applies memory to retain region-specific rules across interactions, improving accuracy over repeated use.

## Functional Requirements

- Build one Agent Kernel agent named `waste_sorting_advisor`.
- Advise users whether an item belongs in recycling, compost, landfill, hazardous waste, e-waste, store drop-off, or another local category.
- Use a lookup tool before giving disposal advice.
- Accept item, material, and optional region inputs.
- Store remembered region-specific rules in session memory.
- Reuse remembered regional rules across later interactions in the same session.
- Provide concise recommendations with the category, reason, and any local-rule caution.

## Local Development

- Provide a local CLI entry point for testing the agent.
- Use `uv` for dependency management.
- Keep generated dependency exports, deployment packages, local virtual environments, and installed coding-agent skills out of Git.

## Deployment

- Follow the deployment folder structure used by the Agent Kernel AWS serverless examples.
- Keep a single `lambda.py` Lambda entry point for the agent.
- Define deployment packaging commands in `deploy/deploy.sh`.
- Do not commit generated requirements files; generate dependency exports during packaging.
- Keep the underlying agent and tool logic shared between local and deployed execution.
