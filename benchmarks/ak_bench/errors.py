class BenchError(Exception):
    """Every refusal or failure the CLI turns into exit code 1."""


class BenchConfigError(BenchError):
    """ak-bench.yaml and CLI argument problems."""


class HostRefused(BenchError):
    """StageFetchers.validate() failures."""


class StepRefused(BenchError):
    """Step folder exists, unknown step, torn-down deployment; post-run before finish."""


class DeploymentLocked(BenchError):
    """Another command is working on the deployment (its lock in state.json is held)."""


class ScriptFailed(BenchError):
    """deploy.sh / destroy.sh exit code != 0, or a missing deployment.json."""


class FetcherTypeError(BenchError):
    """fetch() returned another type than the family's."""
