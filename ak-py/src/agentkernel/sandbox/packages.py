"""Package-spec validation and installer invocation for ``install_packages``.

``PackageInstaller`` turns a package request into a validated installer argv (or a command
string for SDKs that accept only one). Validation is a fixed baseline followed by the
ecosystem's rule chain: the built-in ``PackageSpecRule`` for ``python``/``node``, then any
bring-your-own rule named in the provider block's ``package_rules``. A rejected spec raises
``ValueError`` naming the entry's index and the broken rule, never the entry text, so no
package text reaches any log.
"""

import re
import shlex
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Mapping, Optional

from ..core.util.factory import resolve_dotted
from .errors import SandboxCapabilityError, SandboxConfigError


class PackageSpecRule(ABC):
    """Validates package specs of one ecosystem's grammar. Bring-your-own rules subclass this.

    A rule is instantiated with no arguments. For a built-in ecosystem it runs after the
    built-in rule, so it can only narrow what that ecosystem accepts.
    """

    @abstractmethod
    def validate(self, packages: list[str]) -> None:
        """Raise ValueError naming the index and the broken rule; never echo the entry."""


class _PatternPackageSpecRule(PackageSpecRule):
    """A built-in rule: explicit rejections with their own messages, then a full-match grammar."""

    PATTERN: ClassVar[re.Pattern[str]]
    GRAMMAR: ClassVar[str]  # human description of PATTERN, used in the error message

    def validate(self, packages: list[str]) -> None:
        """Check each entry against the explicit rejections, then the grammar."""
        for index, entry in enumerate(packages):
            reason = self._explicit_rejection(entry)
            if reason is None and not self.PATTERN.fullmatch(entry):
                reason = f"is not {self.GRAMMAR}"
            if reason is not None:
                raise ValueError(f"package {index}: {reason}")

    @abstractmethod
    def _explicit_rejection(self, entry: str) -> Optional[str]:
        """The rule an entry breaks before the grammar is checked, or None."""


class PythonPackageSpecRule(_PatternPackageSpecRule):
    """'python': PyPI registry specs — a name with optional extras and version specifiers."""

    PATTERN = re.compile(
        r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?(?:\[[A-Za-z0-9._-]+(?:,[A-Za-z0-9._-]+)*\])?"
        r"(?:(?:===|==|!=|<=|>=|~=|<|>)[A-Za-z0-9.*+!_-]+(?:,(?:===|==|!=|<=|>=|~=|<|>)[A-Za-z0-9.*+!_-]+)*)?$"
    )
    GRAMMAR = "a registry spec (name, optional [extras], optional version specifiers; no markers or direct references)"
    # pip's ARCHIVE_EXTENSIONS: pip installs a bare entry with any of these suffixes as a local file.
    _ARCHIVE_SUFFIXES: ClassVar[tuple[str, ...]] = (
        ".zip",
        ".whl",
        ".tar.bz2",
        ".tbz",
        ".tar.gz",
        ".tgz",
        ".tar",
        ".tar.xz",
        ".txz",
        ".tlz",
        ".tar.lz",
        ".tar.lzma",
    )

    def _explicit_rejection(self, entry: str) -> Optional[str]:
        if entry.startswith("git+"):
            return "VCS specs (git+) are not allowed"
        if "/" in entry:
            return "paths are not allowed ('/')"
        if entry.lower().endswith(self._ARCHIVE_SUFFIXES):
            return "archive files are not allowed"
        return None


class NodePackageSpecRule(_PatternPackageSpecRule):
    """'node': npm-registry specs — name or @scope/name, optionally @version-or-range."""

    PATTERN = re.compile(r"^(?:@[A-Za-z0-9][A-Za-z0-9._~-]*/)?[A-Za-z0-9][A-Za-z0-9._~-]*(?:@[A-Za-z0-9.^~<>=*|+_-]+)?$")
    GRAMMAR = "a registry spec (name or @scope/name, optional @version or range)"
    _PROTOCOLS: ClassVar[tuple[str, ...]] = ("github:", "git+", "file:", "link:", "npm:")
    # npm-package-arg treats a bare entry with any of these suffixes as a local file.
    _TARBALL_SUFFIXES: ClassVar[tuple[str, ...]] = (".tgz", ".tar.gz", ".tar")

    def _explicit_rejection(self, entry: str) -> Optional[str]:
        if any(protocol in entry for protocol in self._PROTOCOLS):
            return "protocol specs (github:, git+, file:, link:, npm:) are not allowed"
        if entry.lower().endswith(self._TARBALL_SUFFIXES):
            return "tarballs (.tgz, .tar.gz, .tar) are not allowed"
        # Only the scope separator of '@scope/name' may contain '/'; this rejects 'user/repo' shorthand.
        if entry.count("/") != (1 if entry.startswith("@") else 0):
            return "'/' is allowed only as the @scope/name separator"
        return None


class PackageSpecRuleFactory:
    """Resolves an ecosystem key to its rule chain (#541 shape: built-in branches + resolve_dotted)."""

    BUILTIN: ClassVar[tuple[str, ...]] = ("python", "node")

    @classmethod
    def resolve(cls, ecosystem: str, package_rules: Mapping[str, str]) -> list[PackageSpecRule]:
        """The built-in rule, if any, then the bring-your-own rule from package_rules, if any;
        SandboxConfigError when neither exists or a dotted path does not resolve to a PackageSpecRule."""
        chain: list[PackageSpecRule] = []
        if ecosystem == "python":
            chain.append(PythonPackageSpecRule())
        elif ecosystem == "node":
            chain.append(NodePackageSpecRule())
        path = package_rules.get(ecosystem)
        if path is not None:
            chain.append(resolve_dotted(path, base=PackageSpecRule, error=SandboxConfigError)())
        if not chain:
            raise SandboxConfigError(
                f"package ecosystem '{ecosystem}' has no rule; expected one of {cls.BUILTIN} "
                "or a package_rules entry naming a PackageSpecRule subclass"
            )
        return chain

    @classmethod
    def validate_config(cls, sandbox_config: Any) -> None:
        """Startup check: resolve every package_installers key of every profile's provider block."""
        for name, profile in sandbox_config.profiles.items():
            block = getattr(profile, profile.type, None)
            installers = getattr(block, "package_installers", None)
            if installers is None:
                continue  # a provider without package installers (or a dotted-path type)
            for ecosystem in installers:
                try:
                    cls.resolve(ecosystem, block.package_rules)
                except SandboxConfigError as exc:
                    raise SandboxConfigError(f"sandbox profile '{name}': {exc}") from exc


class PackageInstaller:
    """Turns a package request into a validated installer invocation. Shared by docker, kubernetes, e2b, daytona.

    Immutable after construction, so one instance is safe to share across threads. An
    ecosystem with no installer is validated against the baseline only: whether it is declared
    is the handle's check, and an agent-side copy must not reject what the worker may accept.
    """

    def __init__(self, installers: Mapping[str, list[str]], rules: Mapping[str, list[PackageSpecRule]]) -> None:
        missing = [ecosystem for ecosystem in installers if not rules.get(ecosystem)]
        if missing:
            raise SandboxConfigError(f"package ecosystems {missing} have an installer but no rule")
        self._installers: dict[str, tuple[str, ...]] = {ecosystem: tuple(argv) for ecosystem, argv in installers.items()}
        self._rules: dict[str, tuple[PackageSpecRule, ...]] = {ecosystem: tuple(chain) for ecosystem, chain in rules.items()}

    @classmethod
    def from_config(cls, config: Any) -> "PackageInstaller":
        """Build from a _SandboxProviderPackageConfig block, resolving rules through the factory."""
        rules = {ecosystem: PackageSpecRuleFactory.resolve(ecosystem, config.package_rules) for ecosystem in config.package_installers}
        return cls(config.package_installers, rules)

    @property
    def ecosystems(self) -> list[str]:
        """The declared ecosystem keys, in config order."""
        return list(self._installers)

    def validate(self, packages: list[str], ecosystem: str) -> None:
        """Baseline, then every rule in the ecosystem's chain. ValueError on rejection."""
        self.check_baseline(packages)
        for rule in self._rules.get(ecosystem, ()):
            rule.validate(packages)

    def argv(self, packages: list[str], ecosystem: str) -> list[str]:
        """validate(), then the configured prefix + one argument per package."""
        prefix = self._installers.get(ecosystem)
        if prefix is None:
            raise SandboxCapabilityError(f"package_ecosystem:{ecosystem}")
        self.validate(packages, ecosystem)
        return [*prefix, *packages]

    def command(self, packages: list[str], ecosystem: str) -> str:
        """shlex.join(argv(...)), for SDKs that accept only a command string."""
        return shlex.join(self.argv(packages, ecosystem))

    @staticmethod
    def check_baseline(packages: list[str]) -> None:
        """Ecosystem-independent rejections that run before any rule, so no rule can loosen them.
        The worker also runs it before any install override, so a custom provider gets the same floor."""
        # A bare string would iterate as characters and each would pass as a one-letter name.
        if not isinstance(packages, list):
            raise ValueError("packages must be a list of package specs")
        if not packages:
            raise ValueError("packages must not be empty")
        for index, entry in enumerate(packages):
            reason = PackageInstaller._baseline_rejection(entry)
            if reason is not None:
                raise ValueError(f"package {index}: {reason}")

    @staticmethod
    def _baseline_rejection(entry: Any) -> Optional[str]:
        """The baseline rule an entry breaks, or None."""
        if not isinstance(entry, str):
            return "must be a string"
        if not entry:
            return "must not be empty"
        if entry.startswith("-"):
            return "must not start with '-' (installer options are not allowed)"
        if "\x00" in entry:
            return "must not contain NUL"
        if any(char.isspace() for char in entry):
            return "must not contain whitespace"
        if "://" in entry:
            return "URLs are not allowed"
        if entry.startswith((".", "/", "~")):
            return "local paths are not allowed"
        return None
