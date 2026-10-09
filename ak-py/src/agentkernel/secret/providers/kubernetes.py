"""KubernetesSecretProvider — Kubernetes Secrets mounted into the pod as files.

Each Secret is its own volume at {mount_path}/{secret-name}/, one file per data key. The key
OPENAI_API_KEY is read from the one file of that name across the mounted Secrets.
"""

import logging
import os
from typing import Optional

from ...core.config import _SecretConfig
from ...core.util.factory import AKConfigError
from ..base import SecretProvider
from ..errors import SecretError


class KubernetesSecretProvider(SecretProvider):
    """Kubernetes Secrets mounted as volumes under mount_path; never calls the API server."""

    _log = logging.getLogger("ak.secret.provider.kubernetes")

    def __init__(self, mount_path: str) -> None:
        """:raises AKConfigError: If mount_path is empty or not absolute. Touches no file."""
        if not mount_path or not os.path.isabs(mount_path):
            raise AKConfigError(
                "secret.provider.kubernetes.mount_path (AK_SECRET__PROVIDER__KUBERNETES__MOUNT_PATH) must be a "
                f"non-empty absolute directory path, got '{mount_path}'"
            )
        self._mount_path = mount_path

    @classmethod
    def create(cls, config: _SecretConfig) -> "KubernetesSecretProvider":
        """Build from `secret.provider.kubernetes.mount_path`.

        :raises AKConfigError: If the mount path is empty or relative.
        """
        return cls(mount_path=config.provider.kubernetes.mount_path)

    def get_secret(self, key: str) -> Optional[str]:
        """Return the content of the one file named `key` under mount_path, or None if there is none.

        :raises ValueError: If key is not a single, non-hidden path component.
        :raises SecretError: If mount_path is missing or not a directory, the key exists in more
                             than one place, or a file cannot be listed, read or decoded.
        """
        if not key or key.startswith(".") or "/" in key or os.sep in key:
            raise ValueError(f"invalid secret key {key!r}: must be a single, non-hidden path component")
        candidates = self._find_candidates(key)
        if not candidates:
            self._log.debug("No file named %s under %s", key, self._mount_path)
            return None
        if len(candidates) > 1:
            raise SecretError(f"secret '{key}' is defined more than once: {', '.join(sorted(candidates))}")
        return self._read(candidates[0])

    def _find_candidates(self, key: str) -> list[str]:
        """List mount_path once and return every path that resolves to a regular file named `key`."""
        candidates: list[str] = []
        try:
            with os.scandir(self._mount_path) as entries:
                for entry in entries:
                    if entry.name.startswith("."):
                        continue
                    if entry.name == key and entry.is_file():
                        candidates.append(os.path.join(self._mount_path, key))
                    elif entry.is_dir():
                        path = os.path.join(self._mount_path, entry.name, key)
                        if os.path.isfile(path):
                            candidates.append(path)
        except (FileNotFoundError, NotADirectoryError) as exc:
            raise SecretError(
                f"Kubernetes secret mount '{self._mount_path}' is missing or not a directory: set secretStore.enabled "
                "and secretStore.secrets in the Helm chart, mount the Secrets there, or correct "
                "secret.provider.kubernetes.mount_path"
            ) from exc
        except OSError as exc:
            raise SecretError(f"cannot list Kubernetes secret mount '{self._mount_path}': {type(exc).__name__}") from exc
        return candidates

    def _read(self, path: str) -> Optional[str]:
        """Return the file content verbatim; None when it is empty or vanished since discovery."""
        try:
            with open(path, "rb") as handle:
                raw = handle.read()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise SecretError(f"cannot read Kubernetes secret file '{path}': {type(exc).__name__}") from exc
        try:
            value = raw.decode("utf-8")
        except UnicodeDecodeError:
            # Not chained: the decode error text quotes the offending byte, which is secret material.
            raise SecretError(f"Kubernetes secret file '{path}' is not valid UTF-8") from None
        return value or None
