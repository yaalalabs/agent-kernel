import argparse
import os
import sys
from pathlib import Path

from ak_bench.config import BenchConfig, TestType
from ak_bench.errors import BenchError
from ak_bench.run.commands import Deploy, Finish, Plot, PostRun, Run, Step

DEFAULT_DEPLOY_ROOT = Path(__file__).resolve().parent.parent / "app" / "deploy"

FORCE_UNLOCK_HELP = (
    "clear a deployment lock held from another machine and run no step. Use it only once the command on that machine is known to be "
    "dead (its process was killed or the machine is gone); prints who held the lock and since when, and asks for confirmation"
)


class BenchCli:
    """argparse front end: one sub-command per command class."""

    def __init__(self) -> None:
        self.parser = self._build_parser()

    def run(self, argv: list[str]) -> int:
        args = self.parser.parse_args(argv)
        if args.config is not None:
            # BenchConfig.get() reads the file from here, as AKConfig does from AK_CONFIG_PATH_OVERRIDE.
            os.environ[BenchConfig.yaml_file_env_var] = str(args.config)
        if args.command == "step":
            self._check_step_args(args)
        try:
            self._execute(args, (BenchConfig.get(), args.results_dir, args.deploy_root))
        except BenchError as e:
            print(f"ak-bench {args.command}: {e}", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print(f"ak-bench {args.command}: interrupted", file=sys.stderr)
            return 130
        return 0

    @staticmethod
    def _execute(args: argparse.Namespace, ctx: tuple) -> None:
        match args.command:
            case "deploy":
                Deploy(*ctx).execute(args.host, args.mode, args.message_type, args.run_id)
            case "step" if args.force_unlock:
                Step(*ctx).force_unlock(args.deployment, args.yes)
            case "step":
                Step(*ctx).execute(args.deployment, args.test_type, args.step, args.replace)
            case "plot":
                Plot(*ctx).execute(args.deployment, args.run_id)
            case "finish":
                Finish(*ctx).execute(args.deployment)
            case "post-run":
                PostRun(*ctx).execute(args.deployment, args.run_id)
            case "run":
                Run(*ctx).execute(args.host, args.mode, args.message_type, args.steps)

    def _check_step_args(self, args: argparse.Namespace) -> None:
        if args.force_unlock:
            if args.test_type or args.step is not None or args.replace:
                self.parser.error("step: --force-unlock can't be combined with --test-type, --step or --replace")
        elif args.test_type is None or args.step is None:
            self.parser.error("step: --test-type and --step are required (or use --force-unlock)")
        elif args.yes:
            self.parser.error("step: --yes is only valid with --force-unlock")

    @staticmethod
    def _build_parser() -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog="ak-bench", description="Agent Kernel benchmark harness")
        parser.add_argument("--config", type=Path, help="benchmark config file (default: $AK_BENCH_CONFIG_PATH_OVERRIDE, else ./ak-bench.yaml)")
        parser.add_argument("--results-dir", type=Path, default=Path("results"), help="results root (default: ./results)")
        parser.add_argument("--deploy-root", type=Path, default=DEFAULT_DEPLOY_ROOT, help="folder holding the deployment folders")
        sub = parser.add_subparsers(dest="command", required=True)

        deploy = sub.add_parser("deploy", help="deploy one host x mode x message type")
        deploy.add_argument("--host", required=True)
        deploy.add_argument("--mode", required=True)
        deploy.add_argument("--message-type", required=True)
        deploy.add_argument("--run-id", help="put the deployment in this existing run (default: a new run id)")

        step = sub.add_parser("step", help="run one step on a deployment")
        step.add_argument("--deployment", required=True)
        step.add_argument("--test-type", choices=list(TestType))
        step.add_argument("--step", type=int, help="one of the deployment's load steps")
        step.add_argument("--replace", action="store_true", help="replace an existing step folder")
        step.add_argument("--force-unlock", action="store_true", help=FORCE_UNLOCK_HELP)
        step.add_argument("--yes", action="store_true", help="with --force-unlock: skip the confirmation prompt")

        for name, help_text in (("plot", "draw every graph from the CSVs so far"), ("post-run", "run the after_teardown fetchers and re-plot")):
            cmd = sub.add_parser(name, help=help_text)
            target = cmd.add_mutually_exclusive_group(required=True)
            target.add_argument("--deployment")
            target.add_argument("--run-id")

        finish = sub.add_parser("finish", help="run after_all_steps, tear down, say whether post-run is needed")
        finish.add_argument("--deployment", required=True)

        run = sub.add_parser("run", help="deploy, run every step, plot and finish for each selection")
        run.add_argument("--host", action="append", help="repeatable; default: config hosts, else all")
        run.add_argument("--mode", action="append", help="repeatable; default: config modes, else all")
        run.add_argument("--message-type", action="append", help="repeatable; default: config message_types, else all")
        run.add_argument("--steps", type=int, action="append", help="repeatable; a subset of the config load_steps")
        return parser


def main() -> None:
    sys.exit(BenchCli().run(sys.argv[1:]))
