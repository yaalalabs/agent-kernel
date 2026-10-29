# Agent Kernel MAF API Example

This package contains a demo of Agent Kernel exposing agents built with Microsoft Agent Framework via a REST API.

Install dependencies using:

    ./build.sh

> Note: until a release of `agentkernel` that includes the `maf` extra is published to PyPI,
> build with `./build.sh local` against a locally built `ak-py/dist`; a plain `./build.sh` installs a
> PyPI release without `agentkernel.maf`.

Install local dependencies in development mode using:

    ./build.sh local

Run this demo using the following:

    uv run app.py

To run tests:
    uv run pytest app_test.py -v
