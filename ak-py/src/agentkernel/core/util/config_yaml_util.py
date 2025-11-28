## This is an adaptation of the pydantic_settings_yaml package to better suit the needs of AgentKernel.
## Original package at: https://pypi.org/project/pydantic-settings-yaml/
# MIT License

# Copyright (c) 2022 Nelen & Schuurmans

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import os
import re
from pathlib import Path
from typing import Any, Dict, Tuple, Type

import yaml
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


def replace_secrets(secrets_dir: Path, data: str) -> str:
    """
    Replace "<file:xxxx>" secrets in given data

    """
    pattern = re.compile(r"\<file\:([^>]*)\>")

    for match in pattern.findall(data):
        relpath = Path(match)
        path = secrets_dir / relpath

        if not path.exists():
            raise FileNotFoundError(f"Secret file referenced in yaml file not found: {path}")

        data = data.replace(f"<file:{match}>", path.read_text("utf-8"))
    return data


def yaml_config_settings_source(settings: "YamlBaseSettingsModified") -> Dict[str, Any]:
    """Loads settings from a YAML file at `Config.yaml_file`

    "<file:xxxx>" patterns are replaced with the contents of file xxxx. The root path
    where to find the files is configured with `secrets_dir`.
    """
    secrets_dir = os.environ.get("AK_SECRETS_PATH", None)
    yaml_file = os.environ.get("AK_CONFIG_PATH_OVERRIDE", "config.yaml")

    path = Path(yaml_file)

    if not path.exists():
        print(f"WARNING: Could not open yaml settings file at: {path}")
        return {}

    if secrets_dir is not None:
        secrets_path = Path(secrets_dir)
        return yaml.safe_load(replace_secrets(secrets_path, path.read_text("utf-8")))

    return yaml.safe_load(path.read_text("utf-8"))


class YamlConfigSettingsSource(PydanticBaseSettingsSource):
    """
    A simple settings source class that loads variables from a YAML file

    Note: slightly adapted version of JsonConfigSettingsSource from docs.
    """

    def __init__(self, settings_class):
        super().__init__(settings_class)
        self._yaml_data = yaml_config_settings_source(settings_class)

    def get_field_value(self, field: FieldInfo, field_name: str) -> Tuple[Any, str, bool]:
        field_value = self._yaml_data.get(field_name)
        return field_value, field_name, False

    def prepare_field_value(self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool) -> Any:
        return value

    def __call__(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {}

        for field_name, field in self.settings_cls.model_fields.items():
            field_value, field_key, value_is_complex = self.get_field_value(field, field_name)
            field_value = self.prepare_field_value(field_name, field, field_value, value_is_complex)
            if field_value is not None:
                d[field_key] = field_value

        return d


class YamlBaseSettingsModified(BaseSettings):
    """Allows to specify a 'yaml_file' path in the Config section.

    The secrets injection is done differently than in BaseSettings, allowing also
    partial secret replacement (such as "postgres://user:<file:path-to-password>@...").

    Field value priority:

    1. Arguments passed to the Settings class initialiser.
    2. Variables from Config.yaml_file (reading secrets at "<file:xxxx>" entries)
    3. Environment variables
    4. Variables loaded from a dotenv (.env) file (if Config.env_file is set)
    5. Variables from secrets in files one directory.
       (Note: the replace_secrets function  above does not use this method and provides
        a more explicit way of specifying the exact path to the secret file)

    Default paths:

    - secrets_dir: "/etc/secrets" or env.SETTINGS_SECRETS_DIR
    - yaml_file: "/etc/config/config.yaml" or env.SETTINGS_YAML_FILE

    See also:

      https://pydantic-docs.helpmanual.io/usage/settings/
    """

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        """
        Define the sources and their order for loading the settings values.

        :param settings_cls: The Settings class.
        :param init_settings: The `InitSettingsSource` instance.
        :param env_settings: The `EnvSettingsSource` instance.
        :param dotenv_settings: The `DotEnvSettingsSource` instance.
        :param file_secret_settings: The `SecretsSettingsSource` instance.
        :return: A tuple containing the sources and their order for
            loading the settings values.
        """
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        env_prefix="AK_",
        extra="ignore",
        env_ignore_empty=True,
    )
