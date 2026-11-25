class BenchError(Exception):
    """Every refusal or failure the CLI turns into exit code 1."""


class BenchConfigError(BenchError):
    """ak-bench.yaml and CLI argument problems."""


class HostRefused(BenchError):
    """StageFetchers.validate() failures."""


class StepRefused(BenchError):
    """Lock held, step folder exists, unknown step, torn-down deployment."""


class ScriptFailed(BenchError):
    """deploy.sh / destroy.sh exit code != 0, or a missing deployment.json."""


class FetcherTypeError(BenchError):
    """fetch() returned another type than the family's."""
