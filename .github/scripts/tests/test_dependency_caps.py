"""dependency_caps.py `bounds`: every lock keeps a repo package's direct dependencies inside that package's bounds."""

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dependency_caps
from dependency_caps import Bounds, Repo, State

LOCK_HEAD = 'version = 1\nrevision = 3\nrequires-python = ">=3.12"\n'


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


class BoundsTest(unittest.TestCase):
    """A fake repo: `ak-py` declares foo>=1.2,<2.0.0 and, in an extra, bar>=2,<3; examples lock agentkernel from PyPI."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.write(
            "ak-py/pyproject.toml",
            _pyproject("agentkernel", ["foo>=1.2,<2.0.0"], {"auth": ["bar>=2,<3"]}, {"dev": ["foo>=3"]}),
        )
        self.write("ak-py/uv.lock", _lock(("agentkernel", "0.9.5"), ("foo", "1.3.1"), ("bar", "2.1")))
        self.write("examples/good/pyproject.toml", _pyproject("good", ["agentkernel[auth]>=0.9.5"]))
        self.write(
            "examples/good/uv.lock",
            _lock(("agentkernel", "0.9.5"), ("foo", "1.3.1"), ("bar", "2.5"), root="good", extras=["auth"]),
        )
        self.write("examples/bad/pyproject.toml", _pyproject("bad", ["agentkernel[auth]>=0.9.5"]))
        self.write(
            "examples/bad/uv.lock",
            _lock(("agentkernel", "0.9.5"), ("foo", "3.0.1"), ("bar", "3.2"), root="bad", extras=["auth"]),
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
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        self.state = State(self.root / "state")
        self.repo = Repo(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    @staticmethod
    def _found(violations: list[dict]) -> set[tuple[str, str, str, str]]:
        return {(v["manifest"], v["package"], v["version"], v["requirement"]) for v in violations}

    def test_a_lock_outside_the_declared_bounds_is_a_violation(self):
        found = self._found(Bounds(self.repo, self.state, check_only=True).violations())
        self.assertIn(("examples/bad/pyproject.toml", "foo", "3.0.1", ">=1.2,<2.0.0"), found)
        self.assertIn(("examples/bad/pyproject.toml", "bar", "3.2", ">=2,<3"), found)

    def test_a_lock_inside_the_bounds_and_the_source_itself_are_not(self):
        manifests = {v["manifest"] for v in Bounds(self.repo, self.state, check_only=True).violations()}
        self.assertNotIn("examples/good/pyproject.toml", manifests)
        self.assertNotIn("ak-py/pyproject.toml", manifests)

    def test_a_lock_without_the_repo_package_is_not_checked(self):
        manifests = {v["manifest"] for v in Bounds(self.repo, self.state, check_only=True).violations()}
        self.assertNotIn("examples/other/pyproject.toml", manifests)

    def test_every_locked_version_is_checked(self):
        found = self._found(Bounds(self.repo, self.state, check_only=True).violations())
        self.assertIn(("examples/multi/pyproject.toml", "foo", "3.0.1", ">=1.2,<2.0.0"), found)
        self.assertNotIn(("examples/multi/pyproject.toml", "foo", "1.3.1", ">=1.2,<2.0.0"), found)

    def test_an_extra_the_lock_does_not_install_bounds_nothing(self):
        manifests = {v["manifest"] for v in Bounds(self.repo, self.state, check_only=True).violations()}
        self.assertNotIn("examples/noextra/pyproject.toml", manifests)

    def test_dependency_groups_do_not_bound_anyone(self):
        """A dev group is not in the wheel's metadata: foo>=3 in ak-py's dev group must not flag foo 1.3.1."""
        found = self._found(Bounds(self.repo, self.state, check_only=True).violations())
        self.assertNotIn(("examples/good/pyproject.toml", "foo", "1.3.1", ">=3"), found)

    def test_each_violation_names_the_source_package(self):
        [bad] = [
            v
            for v in Bounds(self.repo, self.state, check_only=True).violations()
            if v["manifest"] == "examples/bad/pyproject.toml" and v["package"] == "foo"
        ]
        self.assertEqual(bad["source"], "agentkernel")

    def test_check_fails_and_lists_each_drift(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = Bounds(self.repo, self.state, check_only=True).run()
        self.assertEqual(code, 1)
        self.assertIn("examples/bad/pyproject.toml: foo 3.0.1 is outside agentkernel's >=1.2,<2.0.0", out.getvalue())
        self.assertIn("uv lock --upgrade-package", out.getvalue())

    def test_check_passes_quietly_when_nothing_drifted(self):
        self.write(
            "examples/bad/uv.lock",
            _lock(("agentkernel", "0.9.5"), ("foo", "1.3.1"), ("bar", "2.5"), root="bad", extras=["auth"]),
        )
        self.write("examples/multi/uv.lock", _lock(("agentkernel", "0.9.5"), ("foo", "1.3.1"), root="multi"))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(Bounds(self.repo, self.state, check_only=True).run(), 0)

    def test_fix_relocks_each_drifted_lock_with_the_bounds_and_records_the_moves(self):
        commands = []

        def relock(command, cwd, log):
            commands.append((command, cwd))
            fixed = {
                "bad": _lock(("agentkernel", "0.9.5"), ("foo", "1.3.1"), ("bar", "2.5"), root="bad", extras=["auth"]),
                "multi": _lock(("agentkernel", "0.9.5"), ("foo", "1.3.1"), root="multi"),
            }
            (cwd / "uv.lock").write_text(fixed[cwd.name])
            return 0

        with mock.patch.object(dependency_caps.CommandRunner, "run", side_effect=relock), redirect_stdout(
            io.StringIO()
        ):
            self.assertEqual(Bounds(self.repo, self.state, check_only=False).run(), 0)

        by_dir = {cwd.name: command for command, cwd in commands}
        self.assertEqual(
            by_dir["bad"], ["uv", "lock", "--upgrade-package", "bar>=2,<3", "--upgrade-package", "foo>=1.2,<2.0.0"]
        )
        self.assertEqual(by_dir["multi"], ["uv", "lock", "--upgrade-package", "foo>=1.2,<2.0.0"])
        self.assertNotIn("good", by_dir)
        changes = self.state.load("changes.json", [])
        self.assertIn(
            {
                "kind": "bounds",
                "manifest": "examples/bad/pyproject.toml",
                "package": "foo",
                "old": "3.0.1",
                "new": ">=1.2,<2.0.0",
                "source": "agentkernel",
            },
            changes,
        )
        self.assertEqual(self.state.load("results.json", {}), {})
        self.assertEqual(Bounds(self.repo, self.state, check_only=True).violations(), [])

    def test_a_lock_that_cannot_be_pulled_back_is_marked_failed_for_finalize(self):
        with mock.patch.object(dependency_caps.CommandRunner, "run", return_value=1), redirect_stdout(io.StringIO()):
            self.assertEqual(Bounds(self.repo, self.state, check_only=False).run(), 0)

        results = self.state.load("results.json", {})
        self.assertEqual(results["examples/bad/pyproject.toml"]["status"], "fail")
        self.assertEqual(results["examples/bad/pyproject.toml"]["step"], "uv lock (bounds)")
        self.assertNotIn("examples/good/pyproject.toml", results)
        self.assertEqual([c for c in self.state.load("changes.json", []) if c["kind"] == "bounds"], [])

    def test_a_relock_that_leaves_a_drift_is_marked_failed_too(self):
        with mock.patch.object(dependency_caps.CommandRunner, "run", return_value=0), redirect_stdout(io.StringIO()):
            Bounds(self.repo, self.state, check_only=False).run()

        self.assertEqual(self.state.load("results.json", {})["examples/bad/pyproject.toml"]["step"], "uv lock (bounds)")

    def test_a_bound_the_published_release_contradicts_waits_for_a_release(self):
        """The lock resolves agentkernel from PyPI; when that release itself requires a version outside the
        branch's bound, no re-lock can satisfy both. It is reported, not failed: `finalize` would otherwise put
        back the manifest's whole update for a drift only a release can fix."""
        commands = []

        def relock(command, cwd, log):
            commands.append((cwd.name, command))
            if cwd.name == "bad" and any(arg.startswith("foo") for arg in command):
                log.write_text(
                    "  x No solution found when resolving dependencies:\n"
                    "  ╰─▶ Because agentkernel[auth]==0.9.5 depends on foo>=3,<4 and foo>=1.2,<2.0.0, we can\n"
                    "      conclude that agentkernel[auth]==0.9.5 cannot be used.\n"
                )
                return 1
            fixed = {
                "bad": _lock(("agentkernel", "0.9.5"), ("foo", "3.0.1"), ("bar", "2.5"), root="bad", extras=["auth"]),
                "multi": _lock(("agentkernel", "0.9.5"), ("foo", "1.3.1"), root="multi"),
            }
            (cwd / "uv.lock").write_text(fixed[cwd.name])
            return 0

        with mock.patch.object(dependency_caps.CommandRunner, "run", side_effect=relock), redirect_stdout(
            io.StringIO()
        ):
            self.assertEqual(Bounds(self.repo, self.state, check_only=False).run(), 0)

        # Retried without foo, so bar is still pulled back.
        self.assertEqual([c for d, c in commands if d == "bad"][-1], ["uv", "lock", "--upgrade-package", "bar>=2,<3"])
        self.assertNotIn("examples/bad/pyproject.toml", self.state.load("results.json", {}))
        changes = self.state.load("changes.json", [])
        self.assertIn(
            {
                "kind": "bounds_release",
                "manifest": "examples/bad/pyproject.toml",
                "package": "foo",
                "old": "3.0.1",
                "new": ">=1.2,<2.0.0",
                "source": "agentkernel",
            },
            changes,
        )
        self.assertIn(
            {
                "kind": "bounds",
                "manifest": "examples/bad/pyproject.toml",
                "package": "bar",
                "old": "3.2",
                "new": ">=2,<3",
                "source": "agentkernel",
            },
            changes,
        )

    def test_check_names_the_drift_a_release_must_fix_apart(self):
        """`--check` cannot run the resolver; it says which source a drift belongs to, and the fix that applies."""
        out = io.StringIO()
        with redirect_stdout(out):
            Bounds(self.repo, self.state, check_only=True).run()
        self.assertIn(
            "or, where the release agentkernel resolves from requires otherwise, a new release", out.getvalue()
        )

    def test_a_failed_check_in_update_is_not_overwritten_by_a_passing_bounds(self):
        self.state.save(
            "results.json",
            {
                "examples/good/pyproject.toml": {
                    "manifest": "examples/good/pyproject.toml",
                    "status": "fail",
                    "step": "uv sync",
                    "log": "x",
                }
            },
        )
        with mock.patch.object(dependency_caps.CommandRunner, "run", return_value=1), redirect_stdout(io.StringIO()):
            Bounds(self.repo, self.state, check_only=False).run()

        self.assertEqual(self.state.load("results.json", {})["examples/good/pyproject.toml"]["step"], "uv sync")


if __name__ == "__main__":
    unittest.main()
