"""Public testing helpers for secret providers.

``SecretProviderContract`` is a reusable pytest suite asserting the ABC semantics every
``SecretProvider`` must honor. Subclass it in a test module and override the ``provider`` fixture
and ``seed``; it is deliberately NOT named ``Test*`` so pytest does not collect it on its own.

This module imports ``pytest`` and is therefore only meant to be imported from test code — it is
intentionally left out of ``agentkernel.secret``'s exports so ``import agentkernel.secret`` stays
free of a pytest dependency.
"""

import pytest

from .base import SecretProvider

_KEY_A = "CONTRACT_KEY_A"
_KEY_B = "CONTRACT_KEY_B"
_KEY_PADDED = "CONTRACT_PADDED"
_KEY_MULTILINE = "CONTRACT_MULTILINE"
_KEY_ENV_ONLY = "CONTRACT_ENV_ONLY"
_CONTRACT_KEYS = (_KEY_A, _KEY_B, _KEY_PADDED, _KEY_MULTILINE, _KEY_ENV_ONLY)


class SecretProviderContract:
    """Conformance suite every SecretProvider subclasses. Override `provider` and `seed`.

    One declared capability flag, *read by the suite*, never an ad-hoc skip, so a bring-your-own
    provider gets the same treatment and no provider can quietly opt out of an assertion.

    Not collected on its own — the class name is intentionally not prefixed ``Test``.
    """

    # True for a backend whose store IS the environment (EnvSecretProvider).
    reads_environment: bool = False

    @pytest.fixture
    def provider(self) -> SecretProvider:
        """The provider under contract; every subclass must override this fixture."""
        raise NotImplementedError("subclasses must override the `provider` fixture")

    def seed(self, provider: SecretProvider, key: str, value: str) -> None:
        """Store `value` under `key` in this backend; every subclass must override this."""
        raise NotImplementedError("subclasses must override `seed`")

    @pytest.fixture(autouse=True)
    def _clean_contract_environment(self, monkeypatch):
        """Start every contract test with the contract keys absent from the environment."""
        for key in _CONTRACT_KEYS:
            monkeypatch.delenv(key, raising=False)

    def test_contract_seeded_value_round_trips_verbatim(self, provider):
        padded = "  padded value  "
        multiline = "line1\nline2\n"
        self.seed(provider, _KEY_PADDED, padded)
        self.seed(provider, _KEY_MULTILINE, multiline)

        assert provider.get_secret(_KEY_PADDED) == padded
        assert provider.get_secret(_KEY_MULTILINE) == multiline

    def test_contract_absent_key_returns_none(self, provider):
        assert provider.get_secret(_KEY_A) is None

    def test_contract_key_is_used_verbatim(self, provider):
        self.seed(provider, _KEY_A, "value-a")

        assert provider.get_secret(_KEY_B) is None
        assert provider.get_secret(_KEY_A) == "value-a"

    def test_contract_environment_is_consulted_only_when_declared(self, provider, monkeypatch):
        monkeypatch.setenv(_KEY_ENV_ONLY, "from-environment")

        if self.reads_environment:
            assert provider.get_secret(_KEY_ENV_ONLY) == "from-environment"
        else:
            assert provider.get_secret(_KEY_ENV_ONLY) is None
