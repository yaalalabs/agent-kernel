"""Tests for package-spec validation and rule resolution (``agentkernel.sandbox.packages``):
the installer baseline, the built-in ``python``/``node`` rules, bring-your-own rule chains,
the startup ``validate_config`` check, and the installer's argv/command shapes.
"""

import shlex

import pytest

from agentkernel.core.config import (
    _SandboxConfig,
    _SandboxDaytonaConfig,
    _SandboxDockerConfig,
    _SandboxE2BConfig,
    _SandboxKubernetesConfig,
    _SandboxLocalSubprocessConfig,
    _SandboxProfileConfig,
)
from agentkernel.sandbox.errors import SandboxCapabilityError, SandboxConfigError
from agentkernel.sandbox.packages import (
    NodePackageSpecRule,
    PackageInstaller,
    PackageSpecRule,
    PackageSpecRuleFactory,
    PythonPackageSpecRule,
)


class _AllowAllRule(PackageSpecRule):
    """A permissive BYO rule: accepts anything."""

    def validate(self, packages: list[str]) -> None:
        pass


class _AllowlistRule(PackageSpecRule):
    """A narrowing BYO rule: only names on the allowlist."""

    ALLOWED = {"requests", "numpy"}

    def validate(self, packages: list[str]) -> None:
        for index, entry in enumerate(packages):
            if entry not in self.ALLOWED:
                raise ValueError(f"package {index}: not on the allowlist")


class _NotARule:
    pass


_ALLOW_ALL = f"{__name__}._AllowAllRule"
_ALLOWLIST = f"{__name__}._AllowlistRule"
_NOT_A_RULE = f"{__name__}._NotARule"


def _installer(installers=None, package_rules=None) -> PackageInstaller:
    block = _SandboxDockerConfig(**({} if installers is None else {"package_installers": installers}), package_rules=package_rules or {})
    return PackageInstaller.from_config(block)


def _assert_rejected(validate, packages, entry, index=0):
    """A rejection raises ValueError naming the index, never the entry text."""
    with pytest.raises(ValueError) as excinfo:
        validate(packages)
    message = str(excinfo.value)
    assert f"package {index}" in message
    assert entry not in message


# --------------------------------------------------------------------------- #
# Baseline (PackageInstaller)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "entry",
    ["-zzq", "--index-url=zzqhost", "zzq zzr", "zzq\tzzr", "zzq\x00", "https://zzqhost/p", "./zzqdir", "/zzqdir", "~zzqdir"],
)
def test_baseline_rejects_entry(entry):
    installer = _installer()
    _assert_rejected(lambda packages: installer.validate(packages, "python"), ["requests", entry], entry, index=1)


@pytest.mark.parametrize(
    "entry, reason",
    [
        ("", "must not be empty"),
        (7, "must be a string"),
        ("-zzq", "must not start with '-'"),
        ("zzq zzr", "whitespace"),
        ("zzq\tzzr", "whitespace"),
        ("zzq\x00zzr", "NUL"),
        ("zzqscheme://zzqhost", "URLs are not allowed"),
        (".zzqdir", "local paths"),
        ("/zzqdir", "local paths"),
        ("~zzqdir", "local paths"),
    ],
)
def test_baseline_alone_rejects_entry(entry, reason):
    # The baseline-only installer has no rule chain, so each rejection here is the baseline's own
    # (behind the python rule most of these would be rejected by the grammar anyway).
    installer = PackageInstaller({}, {})
    with pytest.raises(ValueError) as excinfo:
        installer.validate(["requests", entry], "python")
    message = str(excinfo.value)
    assert message.startswith("package 1: ") and reason in message
    if isinstance(entry, str) and entry:
        assert entry not in message


@pytest.mark.parametrize("packages", [[], "requests", ("requests",)])
def test_baseline_rejects_non_list_or_empty(packages):
    # A bare string would otherwise iterate as one-letter package names.
    with pytest.raises(ValueError):
        _installer().validate(packages, "python")


@pytest.mark.parametrize("entry", ["", 42, None])
def test_baseline_rejects_empty_or_non_str_entry(entry):
    with pytest.raises(ValueError, match="package 0"):
        _installer().validate([entry], "python")


def test_baseline_runs_before_a_permissive_byo_rule():
    # A BYO rule can narrow the baseline, never loosen it — even for an ecosystem with no built-in rule.
    installer = _installer({"deb": ["apt-get", "install", "-y"]}, {"deb": _ALLOW_ALL})
    _assert_rejected(lambda packages: installer.validate(packages, "deb"), ["--zzq"], "--zzq")


# --------------------------------------------------------------------------- #
# Built-in rules
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "entry",
    ["requests", "requests==2.31.0", "requests[socks,security]>=2,<3", "numpy~=1.26", "a.b-c_d", "pkg===1.0", "pkg!=1.*", "Django>3"],
)
def test_python_rule_accepts(entry):
    PythonPackageSpecRule().validate([entry])


@pytest.mark.parametrize(
    "entry",
    ["git+zzq", "dist/zzq.whl", "sub/zzq", "zzq.whl", "zzq.tar.gz", "zzq.zip", "zzq.ZIP", "zzq@zzqurl", 'zzq;python_version>"3"', "zzq[", "_zzq"]
    # Every other suffix pip installs as a local archive file.
    + ["zzq.tgz", "zzq.tar", "zzq.tar.bz2", "zzq.tbz", "zzq.tar.xz", "zzq.txz", "zzq.tlz", "zzq.tar.lz", "zzq.tar.lzma"],
)
def test_python_rule_rejects(entry):
    _assert_rejected(PythonPackageSpecRule().validate, [entry], entry)


@pytest.mark.parametrize("entry", ["lodash", "lodash@4.17.21", "@types/node", "@types/node@^20", "react@>=18", "pkg@~1.2.3", "a@1.x||2.x"])
def test_node_rule_accepts(entry):
    NodePackageSpecRule().validate([entry])


@pytest.mark.parametrize(
    "entry",
    [
        "zzq/zzrepo",
        "github:zzq/zzrepo",
        "zzq@file:zzr",
        "link:zzq",
        "npm:zzq",
        "git+zzq",
        "zzq.tgz",
        "zzq.tar.gz",
        "zzq.tar",
        "@zzq/zza/zzb",
        "zzq/",
        "zzq@.",
        "zzq@..",
        "zzq@.1",
    ],
)
def test_node_rule_rejects(entry):
    _assert_rejected(NodePackageSpecRule().validate, [entry], entry)


def test_rule_errors_name_index_not_entry():
    _assert_rejected(PythonPackageSpecRule().validate, ["requests", "numpy", "sub/zzq"], "sub/zzq", index=2)


# --------------------------------------------------------------------------- #
# PackageInstaller: argv / command / ecosystems
# --------------------------------------------------------------------------- #


def test_installer_argv_and_command_shapes():
    installer = _installer({"python": ["pip", "install"], "node": ["npm", "install"]})
    assert installer.ecosystems == ["python", "node"]
    assert installer.argv(["requests", "numpy>=1"], "python") == ["pip", "install", "requests", "numpy>=1"]
    assert installer.argv(["@types/node"], "node") == ["npm", "install", "@types/node"]
    command = installer.command(["numpy>=1"], "python")
    assert command == "pip install 'numpy>=1'"
    assert shlex.split(command) == ["pip", "install", "numpy>=1"]


def test_installer_argv_validates():
    _assert_rejected(lambda packages: _installer().argv(packages, "python"), ["sub/zzq"], "sub/zzq")


def test_installer_undeclared_ecosystem():
    installer = _installer()  # python only
    with pytest.raises(SandboxCapabilityError):
        installer.argv(["lodash"], "node")
    with pytest.raises(SandboxCapabilityError):
        installer.command(["lodash"], "node")
    # validate() runs the baseline only: the handle owns the "declared" check, and the worker decides.
    installer.validate(["lodash"], "node")
    with pytest.raises(ValueError):
        installer.validate(["-r"], "node")


def test_installer_baseline_only():
    installer = PackageInstaller({}, {})
    assert installer.ecosystems == []
    installer.validate(["sub/pkg"], "python")  # no rule chain: the baseline alone accepts it
    with pytest.raises(ValueError):
        installer.validate(["./pkg"], "python")


def test_installer_requires_a_rule_per_installer():
    with pytest.raises(SandboxConfigError):
        PackageInstaller({"deb": ["apt-get", "install"]}, {})


# --------------------------------------------------------------------------- #
# Rule resolution (PackageSpecRuleFactory)
# --------------------------------------------------------------------------- #


def test_factory_resolves_builtins():
    assert [type(rule) for rule in PackageSpecRuleFactory.resolve("python", {})] == [PythonPackageSpecRule]
    assert [type(rule) for rule in PackageSpecRuleFactory.resolve("node", {})] == [NodePackageSpecRule]


def test_factory_byo_rule_for_new_ecosystem():
    chain = PackageSpecRuleFactory.resolve("deb", {"deb": _ALLOW_ALL})
    assert [type(rule) for rule in chain] == [_AllowAllRule]
    installer = _installer({"deb": ["apt-get", "install", "-y"]}, {"deb": _ALLOW_ALL})
    assert installer.argv(["curl"], "deb") == ["apt-get", "install", "-y", "curl"]


def test_factory_byo_rule_runs_after_builtin():
    # A permissive BYO python rule cannot loosen the built-in grammar.
    assert [type(rule) for rule in PackageSpecRuleFactory.resolve("python", {"python": _ALLOW_ALL})] == [PythonPackageSpecRule, _AllowAllRule]
    loose = _installer(package_rules={"python": _ALLOW_ALL})
    _assert_rejected(lambda packages: loose.validate(packages, "python"), ["sub/zzq"], "sub/zzq")  # the built-in rule
    _assert_rejected(lambda packages: loose.validate(packages, "python"), ["./zzq"], "./zzq")  # the baseline

    # A narrowing allowlist rejects an otherwise-valid name.
    narrow = _installer(package_rules={"python": _ALLOWLIST})
    narrow.validate(["requests", "numpy"], "python")
    _assert_rejected(lambda packages: narrow.validate(packages, "python"), ["zzqpkg"], "zzqpkg")


@pytest.mark.parametrize("path", [_NOT_A_RULE, f"{__name__}._Missing", "not_dotted", "zzq_missing_module.Rule"])
def test_factory_bad_rule_path_raises(path):
    with pytest.raises(SandboxConfigError):
        PackageSpecRuleFactory.resolve("deb", {"deb": path})


def test_factory_unknown_ecosystem_without_rule_raises():
    with pytest.raises(SandboxConfigError, match="deb"):
        PackageSpecRuleFactory.resolve("deb", {})
    with pytest.raises(SandboxConfigError):
        _installer({"deb": ["apt-get", "install"]})


# --------------------------------------------------------------------------- #
# Startup check (validate_config)
# --------------------------------------------------------------------------- #


def test_validate_config_accepts_defaults_and_non_package_providers():
    config = _SandboxConfig(
        profiles={
            "docker": _SandboxProfileConfig(type="docker", docker=_SandboxDockerConfig()),
            "k8s": _SandboxProfileConfig(type="kubernetes", kubernetes=_SandboxKubernetesConfig()),
            "e2b": _SandboxProfileConfig(type="e2b", e2b=_SandboxE2BConfig()),
            "daytona": _SandboxProfileConfig(type="daytona", daytona=_SandboxDaytonaConfig()),
            "local": _SandboxProfileConfig(type="local_subprocess", local_subprocess=_SandboxLocalSubprocessConfig()),
            "byo": _SandboxProfileConfig(type="agentkernel.sandbox.testing.FakeSandboxProvider"),
            "missing_block": _SandboxProfileConfig(type="docker"),  # the provider factory reports this, not us
        }
    )
    PackageSpecRuleFactory.validate_config(config)


def test_validate_config_accepts_byo_rule():
    docker = _SandboxDockerConfig(package_installers={"python": ["pip", "install"], "deb": ["apt-get", "install"]}, package_rules={"deb": _ALLOW_ALL})
    PackageSpecRuleFactory.validate_config(_SandboxConfig(profiles={"p": _SandboxProfileConfig(type="docker", docker=docker)}))


def test_validate_config_raises_naming_the_profile():
    docker = _SandboxDockerConfig(package_installers={"deb": ["apt-get", "install"]})
    config = _SandboxConfig(profiles={"apt_box": _SandboxProfileConfig(type="docker", docker=docker)})
    with pytest.raises(SandboxConfigError, match="apt_box"):
        PackageSpecRuleFactory.validate_config(config)


def test_validate_config_covers_single_backend_sugar():
    config = _SandboxConfig(type="e2b", e2b=_SandboxE2BConfig(package_installers={"deb": ["apt-get", "install"]}))
    with pytest.raises(SandboxConfigError, match="default"):
        PackageSpecRuleFactory.validate_config(config)


def test_package_spec_rule_is_public():
    import agentkernel.sandbox as sandbox

    assert sandbox.PackageSpecRule is PackageSpecRule
