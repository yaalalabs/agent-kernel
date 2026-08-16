"""Tests for the lazy `__getattr__` exports in agentkernel.deployment.aws / agentkernel.aws."""

import sys

import agentkernel.deployment.aws as deployment_aws


def test_all_lazy_exports_resolve():
    for name in deployment_aws.__all__:
        assert getattr(deployment_aws, name) is not None


def test_importing_serverless_target_does_not_load_containerized():
    saved_modules = {name: module for name, module in sys.modules.items() if name == "agentkernel" or name.startswith("agentkernel.")}
    for name in saved_modules:
        del sys.modules[name]

    try:
        import agentkernel.aws as aws

        aws.Lambda

        assert "agentkernel.deployment.aws.containerized" not in sys.modules
    finally:
        for name in list(sys.modules):
            if name == "agentkernel" or name.startswith("agentkernel."):
                del sys.modules[name]
        sys.modules.update(saved_modules)
