# Agent Kernel running HuggingFace smolagents Agents on a REST API

This package contains a demo of Agent Kernel running agents built with HuggingFace `smolagents`. Users
can interact with agents via the Agent Kernel REST API. 

## Prerequisites

Be sure to set your HuggingFace token as an environment variable (or export it before testing):

    export HF_TOKEN="your_huggingface_token_here"

## Installation

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

## Running the Demo

Run this demo using the following:

    uv run app.py
