"""dependency_caps.py `bounds`: every lock keeps a repo package's direct dependencies inside that package's bounds."""

import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import ClassVar
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dependency_caps
from dependency_caps import (
    Bounds,
    Checker,
    Holds,
    Manifest,
    Repo,
    Reporter,
    Snapshotter,
    State,
    read_toml,
)

LOCK_HEAD = 'version = 1\nrevision = 3\nrequires-python = ">=3.12"\n'
BAD = "examples/bad/pyproject.toml"


def _package(name: str, version: str) -> str:
    return (
        f'\n[[package]]\nname = "{name}"\nversion = "{version}"\nsource = {{ registry = "https://pypi.org/simple" }}\n'
    )


def _lock(*packages: tuple[str, str], root: str | None = None, extras: list[str] = ()) -> str:
    """A lock with the given packages; `root` adds the project's own entry, which asks agentkernel for `extras`."""
    text = LOCK_HEAD
    if root:
        reference = (
            f'{{ name = "agentkernel", extra = {json.dumps(list(extras))} }}' if extras else '{ name = "agentkernel" }'
        )
        text += f'\n[[package]]\nname = "{root}"\nversion = "0.1.0"\nsource = {{ virtual = "." }}\ndependencies = [\n    {reference},\n]\n'
    return text + "".join(_package(name, version) for name, version in packages)


def _pyproject(
    name: str, dependencies: list[str] = (), extras: dict[str, list[str]] | None = None, groups: dict | None = None
) -> str:
    text = f'[project]\nname = "{name}"\nversion = "0.1.0"\ndependencies = {json.dumps(list(dependencies))}\n'
    if extras:
        text += "\n[project.optional-dependencies]\n" + "".join(f"{k} = {json.dumps(v)}\n" for k, v in extras.items())
    if groups:
        text += "\n[dependency-groups]\n" + "".join(f"{k} = {json.dumps(v)}\n" for k, v in groups.items())
    return text


def _release_error(clause: str, requirement: str) -> str:
    """uv's error when the release the lock resolves requires `requirement` (uv 0.13 says `>=`, older `==`)."""
    return (
        "error: No solution found when resolving dependencies:\n"
        f"  cause: Because agentkernel[auth]{clause} depends on {requirement} and foo>=1.2,<2.0.0, we can\n"
        f"         conclude that agentkernel[auth]{clause} cannot be used.\n"
    )


class FakeUv:
    """`CommandRunner.run` for the tests: each `uv lock` rewrites the lock the way uv would.

    `uv lock --upgrade` and a bare `--upgrade-package <name>` take the newest version the release on PyPI allows
    (LATEST); `--upgrade-package "<name><bound>"` takes the newest inside the bound (INSIDE), and uv moves the
    packages in `also[name]` with it. A package not named keeps its locked version. `fail[name]` is the error a
    pull-back of that package prints before failing; `sync` is the install check's exit code.
    """

    LATEST: ClassVar[dict[str, str]] = {
        "agentkernel": "0.9.5",
        "foo": "3.0.1",
        "bar": "3.2",
        "baz": "1.5",
        "qux": "0.17.7",
    }
    INSIDE: ClassVar[dict[str, str]] = {"foo": "1.3.1", "bar": "2.5", "qux": "0.20.1"}

    def __init__(self, also: dict | None = None, fail: dict | None = None, sync: int = 0):
        self.also = also or {}
        self.fail = fail or {}
        self.sync = sync
        self.commands: list[tuple[str, list[str]]] = []

    def __call__(self, command: list[str], cwd: Path, log: Path) -> int:
        self.commands.append((cwd.name, command))
        if command[:2] == ["uv", "sync"]:
            return self.sync
        lock = cwd / "uv.lock"
        packages = read_toml(lock)["package"]
        root = next(p for p in packages if p.get("source") == {"virtual": "."})
        extras = next(d.get("extra", []) for d in root["dependencies"] if d["name"] == "agentkernel")
        versions = {p["name"]: p["version"] for p in packages if p is not root}
        if command[2:3] == ["--upgrade"]:
            versions = {name: self.LATEST.get(name, version) for name, version in versions.items()}
        for arg in (a for i, a in enumerate(command) if command[i - 1] == "--upgrade-package"):
            name = re.match(r"[\w.-]+", arg)[0]
            if name == arg:
                versions[name] = self.LATEST.get(name, versions.get(name))
                continue
            if name in self.fail:
                with log.open("a") as handle:
                    handle.write(self.fail[name])
                return 1
            versions[name] = self.INSIDE[name]
            versions.update(self.also.get(name, {}))
        lock.write_text(_lock(*sorted(versions.items()), root=root["name"], extras=extras))
        return 0


class BoundsTest(unittest.TestCase):
    """A fake repo: `ak-py` declares foo>=1.2,<2.0.0 and qux>=0.20,<0.21 and, in an extra, bar>=2,<3; examples lock
    agentkernel from PyPI."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.write(
            "ak-py/pyproject.toml",
            _pyproject(
                "agentkernel", ["foo>=1.2,<2.0.0", "qux>=0.20,<0.21"], {"auth": ["bar>=2,<3"]}, {"dev": ["foo>=3"]}
            ),
        )
        self.write("ak-py/uv.lock", _lock(("agentkernel", "0.9.5"), ("foo", "1.3.1"), ("bar", "2.1")))
        self.write("examples/good/pyproject.toml", _pyproject("good", ["agentkernel[auth]>=0.9.5"]))
        self.write(
            "examples/good/uv.lock",
            _lock(("agentkernel", "0.9.5"), ("foo", "1.3.1"), ("bar", "2.5"), root="good", extras=["auth"]),
        )
        self.write(BAD, _pyproject("bad", ["agentkernel[auth]>=0.9.5", "baz"]))
        self.write(
            "examples/bad/uv.lock",
            _lock(
                ("agentkernel", "0.9.5"), ("foo", "3.0.1"), ("bar", "3.2"), ("baz", "1.4"), root="bad", extras=["auth"]
            ),
        )
        # Locks bar 3.2 too, but never installs the `auth` extra that bounds it.
        self.write("examples/noextra/pyproject.toml", _pyproject("noextra", ["agentkernel>=0.9.5", "bar"]))
        self.write(
            "examples/noextra/uv.lock",
            _lock(("agentkernel", "0.9.5"), ("foo", "1.3.1"), ("bar", "3.2"), root="noextra"),
        )
        # Carries foo 3.0.1 but not agentkernel: nothing of this repo's bounds applies to it.
        self.write("examples/other/pyproject.toml", _pyproject("other", ["foo"]))
        self.write("examples/other/uv.lock", _lock(("foo", "3.0.1")))
        # One package locked at two versions (a marker split): the version outside the bound is the drift.
        self.write("examples/multi/pyproject.toml", _pyproject("multi", ["agentkernel>=0.9.5"]))
        self.write(
            "examples/multi/uv.lock", _lock(("agentkernel", "0.9.5"), ("foo", "1.3.1"), ("foo", "3.0.1"), root="multi")
        )
        # Below a floor the branch raised: the pull-back moves qux up, from 0.17 to 0.20.
        self.write("examples/low/pyproject.toml", _pyproject("low", ["agentkernel>=0.9.5"]))
        self.write(
            "examples/low/uv.lock", _lock(("agentkernel", "0.9.5"), ("foo", "1.3.1"), ("qux", "0.17.7"), root="low")
        )
        # Two examples share a project name; one declares baz>=5, which must not bound the other's lock.
        self.write("examples/twin-a/pyproject.toml", _pyproject("twin", ["agentkernel>=0.9.5", "baz>=5"]))
        self.write("examples/twin-a/uv.lock", _lock(("agentkernel", "0.9.5"), ("baz", "5.1"), root="twin"))
        self.write("examples/twin-b/pyproject.toml", _pyproject("twin", ["agentkernel>=0.9.5"]))
        self.write("examples/twin-b/uv.lock", _lock(("agentkernel", "0.9.5"), ("baz", "1.4"), root="twin"))
        git = ["git", "-c", "user.name=test", "-c", "user.email=test@example.com"]
        subprocess.run([*git, "init", "-q"], cwd=self.root, check=True)
        subprocess.run([*git, "add", "."], cwd=self.root, check=True)
        subprocess.run([*git, "commit", "-qm", "base"], cwd=self.root, check=True)
        self.state = State(self.root / "state")
        self.repo = Repo(self.root)
        self.log = self.state.path("logs/test.log")
        self.log.write_text("")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def manifest(self, relative: str = BAD) -> Manifest:
        return Manifest(self.root, relative)

    def violations(self) -> list[dict]:
        bounds = Bounds(self.repo)
        return [v for m in self.repo.manifests() for v in bounds.violations(m)]

    def found(self) -> set[tuple[str, str, str, str]]:
        return {(v["manifest"], v["package"], v["version"], v["requirement"]) for v in self.violations()}

    def pull_back(self, uv: FakeUv, relative: str = BAD, minimums: dict | None = None) -> tuple[int, list[dict]]:
        with mock.patch.object(dependency_caps.CommandRunner, "run", side_effect=uv):
            return Bounds(self.repo).pull_back(self.manifest(relative), self.log, minimums or {})

    @staticmethod
    def outcomes(entries: list[dict]) -> dict[str, str]:
        return {e["package"]: e["outcome"] for e in entries}

    # ---- what counts as a drift ----

    def test_a_lock_outside_the_declared_bounds_is_a_violation(self):
        self.assertIn((BAD, "foo", "3.0.1", ">=1.2,<2.0.0"), self.found())
        self.assertIn((BAD, "bar", "3.2", ">=2,<3"), self.found())
        self.assertIn(("examples/low/pyproject.toml", "qux", "0.17.7", ">=0.20,<0.21"), self.found())

    def test_a_lock_inside_the_bounds_and_the_source_itself_are_not(self):
        manifests = {v["manifest"] for v in self.violations()}
        self.assertNotIn("examples/good/pyproject.toml", manifests)
        self.assertNotIn("ak-py/pyproject.toml", manifests)

    def test_a_lock_without_the_repo_package_is_not_checked(self):
        self.assertNotIn("examples/other/pyproject.toml", {v["manifest"] for v in self.violations()})

    def test_every_locked_version_is_checked(self):
        self.assertIn(("examples/multi/pyproject.toml", "foo", "3.0.1", ">=1.2,<2.0.0"), self.found())
        self.assertNotIn(("examples/multi/pyproject.toml", "foo", "1.3.1", ">=1.2,<2.0.0"), self.found())

    def test_an_extra_the_lock_does_not_install_bounds_nothing(self):
        self.assertNotIn("examples/noextra/pyproject.toml", {v["manifest"] for v in self.violations()})

    def test_dependency_groups_do_not_bound_anyone(self):
        """A dev group is not in the wheel's metadata: foo>=3 in ak-py's dev group must not flag foo 1.3.1."""
        self.assertNotIn(("examples/good/pyproject.toml", "foo", "1.3.1", ">=3"), self.found())

    def test_each_violation_names_the_source_package(self):
        [bad] = [v for v in self.violations() if v["manifest"] == BAD and v["package"] == "foo"]
        self.assertEqual(bad["source"], "agentkernel")

    def test_a_lock_s_own_project_is_not_a_source(self):
        """Examples share project names, and a lock lists its own project: twin-b's lock is not bound by twin-a."""
        self.assertEqual([v for v in self.violations() if v["source"] == "twin"], [])

    # ---- command `bounds` ----

    def test_the_command_fails_and_lists_each_drift(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = Bounds(self.repo).run()
        self.assertEqual(code, 1)
        self.assertIn(f"{BAD}: foo 3.0.1 is outside agentkernel's >=1.2,<2.0.0", out.getvalue())
        self.assertIn('uv lock --upgrade-package "<package><requirement>"', out.getvalue())
        self.assertIn("only a new release fixes", out.getvalue())

    def test_the_command_passes_quietly_when_nothing_drifted(self):
        for relative, packages, root, extras in [
            ("examples/bad/uv.lock", [("foo", "1.3.1"), ("bar", "2.5")], "bad", ["auth"]),
            ("examples/multi/uv.lock", [("foo", "1.3.1")], "multi", []),
            ("examples/low/uv.lock", [("qux", "0.20.1")], "low", []),
        ]:
            self.write(relative, _lock(("agentkernel", "0.9.5"), *packages, root=root, extras=extras))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(Bounds(self.repo).run(), 0)

    # ---- the pull-back ----

    def test_each_drifted_package_is_pulled_back_inside_its_bound(self):
        uv = FakeUv()
        code, entries = self.pull_back(uv)

        self.assertEqual(code, 0)
        self.assertEqual(
            [command for _, command in uv.commands],
            [
                ["uv", "lock", "--upgrade-package", "bar>=2,<3"],
                ["uv", "lock", "--upgrade-package", "foo>=1.2,<2.0.0"],
            ],
        )
        self.assertIn(
            {
                "package": "foo",
                "old": ["3.0.1"],
                "requirement": ">=1.2,<2.0.0",
                "source": "agentkernel",
                "outcome": "pulled",
                "new": "1.3.1",
            },
            entries,
        )
        self.assertEqual(self.outcomes(entries), {"foo": "pulled", "bar": "pulled"})
        self.assertEqual(Bounds(self.repo).violations(self.manifest()), [])

    def test_the_drifted_package_itself_may_leave_its_line_to_reach_the_bound(self):
        """qux 0.17.7 -> 0.20.1 crosses minor lines, but the branch wheel requires it."""
        code, entries = self.pull_back(FakeUv(), "examples/low/pyproject.toml")
        self.assertEqual((code, self.outcomes(entries)), (0, {"qux": "pulled"}))

    def test_a_pull_back_that_takes_another_package_onto_a_new_line_is_put_back(self):
        lock = self.manifest().lock.read_text()
        code, entries = self.pull_back(FakeUv(also={"foo": {"baz": "2.0"}}))

        self.assertEqual(code, 0)
        self.assertEqual(self.outcomes(entries), {"bar": "pulled", "foo": "kept"})
        [kept] = [e for e in entries if e["outcome"] == "kept"]
        self.assertIn("baz 1.4 -> 2.0", kept["note"])
        self.assertEqual(self.manifest().locked()["foo"], "3.0.1")
        self.assertEqual(self.manifest().locked()["baz"], "1.4")
        self.assertNotEqual(self.manifest().lock.read_text(), lock)  # bar's pull-back stays

    def test_a_pull_back_below_a_security_minimum_is_put_back(self):
        code, entries = self.pull_back(FakeUv(also={"foo": {"baz": "1.2"}}), minimums={"baz": "1.4"})

        self.assertEqual((code, self.outcomes(entries)), (0, {"bar": "pulled", "foo": "kept"}))
        [kept] = [e for e in entries if e["outcome"] == "kept"]
        self.assertIn("baz 1.2", kept["note"])
        self.assertIn("security", kept["note"])
        self.assertEqual(self.manifest().locked()["baz"], "1.4")

    def test_a_bound_the_release_rules_out_waits_for_the_next_release(self):
        """uv names the release `agentkernel[auth]>=0.9.5` (0.13), `==0.9.5` (older), or groups every version of
        it: each is recognised."""
        lock = self.manifest().lock.read_text()
        grouped = (
            "error: No solution found when resolving dependencies:\n"
            "  cause: Because all versions of agentkernel[auth] depend on foo>=3,<4 and you require foo>=1.2,<2.0.0,\n"
            "         we can conclude that your requirements are unsatisfiable.\n"
        )
        for error in (_release_error(">=0.9.5", "foo>=3,<4"), _release_error("==0.9.5", "foo>=3,<4"), grouped):
            with self.subTest(error=error.splitlines()[1]):
                self.manifest().lock.write_text(lock)
                self.log.write_text("")
                uv = FakeUv(fail={"foo": error})
                code, entries = self.pull_back(uv)

                self.assertEqual(code, 0)
                self.assertEqual(self.outcomes(entries), {"bar": "pulled", "foo": "release"})
                self.assertEqual(self.manifest().locked()["bar"], "2.5")

    def test_a_release_that_allows_the_bound_does_not_excuse_the_drift(self):
        """The release depends on foo, but foo>=1,<3 admits the bound: something else blocks it, so it fails."""
        code, _ = self.pull_back(FakeUv(fail={"foo": _release_error("==0.9.5", "foo>=1,<3")}))
        self.assertNotEqual(code, 0)

    def test_only_the_failed_attempt_s_output_is_read(self):
        """An earlier attempt's release error in the same log does not excuse a later, unrelated failure."""
        self.log.write_text(_release_error(">=0.9.5", "foo>=3,<4"))
        code, _ = self.pull_back(FakeUv(fail={"foo": "error: Failed to fetch: network unreachable\n"}))
        self.assertNotEqual(code, 0)

    def test_a_pull_back_that_fails_otherwise_fails_the_check(self):
        code, entries = self.pull_back(FakeUv(fail={"bar": "error: Failed to fetch: network unreachable\n"}))
        self.assertNotEqual(code, 0)
        self.assertEqual(entries, [])

    def test_a_pull_back_that_leaves_the_package_outside_fails_the_check(self):
        with mock.patch.object(dependency_caps.CommandRunner, "run", return_value=0):
            code, _ = Bounds(self.repo).pull_back(self.manifest(), self.log, {})
        self.assertNotEqual(code, 0)

    def test_disjoint_reads_each_kind_of_clause(self):
        cases = [
            ("==2.0", "<2.0", True),
            (">=1.89.2,<1.90.dev0", ">=1.95.0,<1.96", True),
            ("~=1.89.2", ">=1.95.0", True),
            ("==1.2.*", ">=1.3", True),
            (">=1,<3", "<2", False),
            (">=1", "!=1.5", False),
            ("<=2.0", ">=2.0", False),
        ]
        for first, second, expected in cases:
            with self.subTest(first=first, second=second):
                self.assertEqual(Bounds.disjoint(first, second), expected)

    # ---- inside the update's checks ----

    def check(self, uv: FakeUv, manifests: list[str] = (BAD,)) -> dict:
        with mock.patch.object(dependency_caps.CommandRunner, "run", side_effect=uv), redirect_stdout(io.StringIO()):
            Checker(self.repo, self.state, 1).run([self.manifest(m) for m in manifests], upgrade=True, holds={})
        return self.state.load("results.json", {})[manifests[0]]

    def test_update_pulls_back_after_the_lock_and_before_the_install_check(self):
        uv = FakeUv()
        result = self.check(uv)

        commands = [command[:3] for _, command in uv.commands]
        self.assertEqual(
            commands,
            [
                ["uv", "lock", "--upgrade"],
                ["uv", "lock", "--upgrade-package"],
                ["uv", "lock", "--upgrade-package"],
                ["uv", "sync", "--frozen"],
            ],
        )
        self.assertEqual((result["status"], result["step"]), ("pass", "uv sync"))
        self.assertEqual(self.outcomes(self.state.load("bounds.json", {})[BAD]), {"foo": "pulled", "bar": "pulled"})
        self.assertEqual(Bounds(self.repo).violations(self.manifest()), [])

    def test_the_install_check_covers_the_pulled_back_lock(self):
        result = self.check(FakeUv(sync=1))
        self.assertEqual((result["status"], result["step"]), ("fail", "uv sync"))

    def test_a_failed_pull_back_fails_the_check_at_its_own_step(self):
        result = self.check(FakeUv(fail={"bar": "error: Failed to fetch: network unreachable\n"}))
        self.assertEqual((result["status"], result["step"]), ("fail", "uv lock (bounds)"))
        self.assertIn("network unreachable", Path(result["log"]).read_text())

    def test_a_failed_lock_is_not_pulled_back_and_keeps_its_log(self):
        uv = FakeUv()

        def failing_lock(command, cwd, log):
            if command[:3] == ["uv", "lock", "--upgrade"]:
                with log.open("a") as handle:
                    handle.write("error: resolver says no\n")
                return 1
            return uv(command, cwd, log)

        result = self.check(failing_lock)
        self.assertEqual((result["status"], result["step"]), ("fail", "uv lock"))
        self.assertIn("resolver says no", Path(result["log"]).read_text())
        self.assertEqual(uv.commands, [])
        self.assertEqual(self.state.load("bounds.json", {})[BAD], [])

    def test_a_hold_re_check_ends_inside_the_bounds_and_the_report_agrees(self):
        """`hold` re-locks from the base lock, which resolves agentkernel's release again and brings the drift
        back; the pull-back runs in that re-check too, so the lock that ships and the report agree."""
        uv = FakeUv()
        with mock.patch.object(dependency_caps.CommandRunner, "run", side_effect=uv), redirect_stdout(io.StringIO()):
            Snapshotter(self.repo, self.state).run()
            Checker(self.repo, self.state, 1).run([self.manifest()], upgrade=True, holds={})
            self.state.path("holds.jsonl").write_text(
                json.dumps({"manifest": BAD, "package": "baz", "reason": "1.5 breaks the example"}) + "\n"
            )
            uv.commands.clear()
            Holds(self.repo, self.state, 1).run()
            Reporter(self.repo, self.state, "1").run()

        relocked = [c for _, c in uv.commands if "foo" in c]  # the hold's re-lock frees foo again (no bound)
        self.assertTrue(relocked, uv.commands)
        self.assertEqual(self.manifest().locked()["baz"], "1.4")
        self.assertEqual(Bounds(self.repo).violations(self.manifest()), [])
        body = self.state.path("pr-body.md").read_text()
        self.assertIn("- `foo` pulled back inside `agentkernel`'s `>=1.2,<2.0.0` (1 manifest(s))", body)

    def test_the_report_lists_each_outcome_and_skips_put_back_manifests(self):
        entry = {"old": ["3.0.1"], "requirement": ">=1.2,<2.0.0", "source": "agentkernel"}
        self.state.save(
            "bounds.json",
            {
                BAD: [
                    {"package": "foo", **entry, "outcome": "release"},
                    {
                        "package": "bar",
                        **entry,
                        "outcome": "kept",
                        "note": "it takes baz 1.4 -> 2.0 onto a new version line",
                    },
                ],
                "examples/multi/pyproject.toml": [{"package": "qux", **entry, "outcome": "pulled", "new": "1.3.1"}],
            },
        )
        self.state.save("reverted.json", ["examples/multi/pyproject.toml"])
        with redirect_stdout(io.StringIO()):
            Reporter(self.repo, self.state, "1").run()

        body = self.state.path("pr-body.md").read_text()
        self.assertIn("- `foo`: the published `agentkernel` requires a version outside its branch bound", body)
        self.assertIn(
            "- `bar` outside `agentkernel`'s `>=1.2,<2.0.0`: it takes baz 1.4 -> 2.0 onto a new version line", body
        )
        self.assertNotIn("`qux` pulled back", body)


if __name__ == "__main__":
    unittest.main()
