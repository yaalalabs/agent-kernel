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


def _isolated_import(*module_names: str, drop_prefixes: tuple = (), touch: tuple = ()) -> set:
    """Import modules into a fresh ``agentkernel`` namespace and return every newly loaded module name.

    ``drop_prefixes`` names third-party packages to unload as well, so the check sees whether this
    import would load them, not whether an earlier test already did.
    """
    prefixes = ("agentkernel", *drop_prefixes)

    def _ours(name: str) -> bool:
        return any(name == prefix or name.startswith(f"{prefix}.") for prefix in prefixes)

    saved_modules = {name: module for name, module in sys.modules.items() if _ours(name)}
    for name in saved_modules:
        del sys.modules[name]
    try:
        import importlib

        for module_name in module_names:
            importlib.import_module(module_name)
        for module_name, attribute in touch:
            getattr(sys.modules[module_name], attribute)
        return set(sys.modules)
    finally:
        for name in list(sys.modules):
            if _ours(name):
                del sys.modules[name]
        sys.modules.update(saved_modules)


def test_importing_the_webhook_handler_does_not_load_the_http_server():
    loaded = _isolated_import("agentkernel.integration.adapter.webhook", drop_prefixes=("uvicorn",))

    assert "agentkernel.integration.adapter.webhook" in loaded
    assert "agentkernel.api.http" not in loaded
    assert "uvicorn" not in loaded


def test_touching_lambda_loads_neither_fastapi_nor_the_webhook_host():
    loaded = _isolated_import("agentkernel.aws", drop_prefixes=("fastapi", "starlette"), touch=(("agentkernel.aws", "Lambda"),))

    assert "agentkernel.deployment.aws.serverless.aklambda" in loaded
    assert "fastapi" not in loaded
    assert "starlette" not in loaded
    assert "agentkernel.deployment.aws.serverless.core.webhook_host" not in loaded


def test_the_authorizer_and_its_bypass_load_neither_fastapi_nor_a_platform_sdk():
    loaded = _isolated_import(
        "agentkernel.deployment.aws.serverless.akauthorizer",
        "agentkernel.integration.adapter",
        drop_prefixes=("fastapi", "starlette", "slack_bolt"),
        touch=(("agentkernel.integration.adapter", "WebhookRouteMatcher"),),
    )

    assert "agentkernel.integration.adapter.route_matcher" in loaded
    assert "fastapi" not in loaded
    assert "slack_bolt" not in loaded


def test_touching_the_webhook_host_through_aws_resolves_it():
    loaded = _isolated_import("agentkernel.aws", touch=(("agentkernel.aws", "LambdaWebhookHost"),))

    assert "agentkernel.deployment.aws.serverless.core.webhook_host" in loaded
