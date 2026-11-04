# Agent Kernel running MAF Agents

This package contains a demo of Agent Kernel running agents built with Microsoft Agent Framework. Users may
interact with agents via the Agent Kernel CLI.

Install dependencies using:

    ./build.sh

> Note: until a release of `agentkernel` that includes the `maf` extra is published to PyPI,
> build with `./build.sh local` against a locally built `ak-py/dist`; a plain `./build.sh` installs a
> PyPI release without `agentkernel.maf`.

Install local dependencies in development mode using:

    ./build.sh local

Run this demo using the following.

    uv run demo.py

To run tests:
    uv run pytest demo_test.py -v
