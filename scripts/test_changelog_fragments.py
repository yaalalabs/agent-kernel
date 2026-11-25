#!/usr/bin/env python3
"""
Unit tests for changelog_fragments.py

Run directly with: python test_changelog_fragments.py
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from changelog_fragments import (
    ChangelogCLI,
    ChangelogConfig,
    Fragment,
    FragmentDirectory,
    PullRequestPolicy,
    ReleaseGuard,
)

REPO_ROOT = SCRIPTS_DIR.parent
CONFIG = ChangelogConfig(
    directory="changelog.d",
    types=("breaking", "added", "changed", "deprecated", "removed", "fixed", "security"),
    ignore=("README.md",),
    orphan_prefix="+",
)


class TempFragments:
    """A temporary repo root with a changelog.d/ holding the given file names."""

    def __init__(self, *names: str):
        self.names = names

    def __enter__(self) -> Path:
        self._dir = tempfile.TemporaryDirectory()
        root = Path(self._dir.name)
        (root / "changelog.d").mkdir()
        for name in self.names:
            (root / "changelog.d" / name).write_text("Entry.\n", encoding="utf-8")
        return root

    def __exit__(self, *exc) -> None:
        self._dir.cleanup()


class TestConfig(unittest.TestCase):
    def test_repo_config_loads_types_in_render_order(self):
        config = ChangelogConfig.load(REPO_ROOT / "towncrier.toml")
        self.assertEqual(config, CONFIG)

    def test_config_without_types_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "towncrier.toml"
            path.write_text('[tool.towncrier]\ndirectory = "changelog.d"\ntype = []\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                ChangelogConfig.load(path)


class TestFragmentParse(unittest.TestCase):
    def test_valid_names(self):
        self.assertEqual(Fragment.parse("664.added.md", CONFIG), Fragment("664.added.md", "664", "added", None))
        self.assertEqual(Fragment.parse("664.added.1.md", CONFIG), Fragment("664.added.1.md", "664", "added", 1))
        self.assertEqual(Fragment.parse("+tidy-logs.fixed.md", CONFIG).issue, "+tidy-logs")
        self.assertEqual(Fragment.parse("870.breaking.md", CONFIG).type, "breaking")

    def test_names_towncrier_would_reject_or_drop(self):
        for name in [
            "700.feature.md",  # unknown type: towncrier build drops it silently
            "added.md",  # no issue part
            "603.added.registry.md",  # text counter: towncrier raises "multiple files"
            "701.added.txt",  # not Markdown
            "abc.added.md",  # issue is not a number and not an orphan
            "+.added.md",  # empty orphan slug
            "664.Added.md",  # type is case-sensitive
        ]:
            with self.subTest(name=name):
                self.assertIsNone(Fragment.parse(name, CONFIG))


class TestFragmentDirectory(unittest.TestCase):
    def test_lists_fragments_and_skips_ignored_files(self):
        with TempFragments("664.added.md", "870.breaking.md", "README.md", "700.feature.md") as root:
            fragments = FragmentDirectory(root, CONFIG)
            self.assertEqual(fragments.names(), ["664.added.md", "700.feature.md", "870.breaking.md"])
            self.assertEqual(fragments.invalid(), ["700.feature.md"])
            self.assertEqual(fragments.of_type("breaking"), ["870.breaking.md"])

    def test_missing_directory_has_no_fragments(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(FragmentDirectory(Path(tmp), CONFIG).names(), [])


class TestPullRequestPolicy(unittest.TestCase):
    def setUp(self):
        self.policy = PullRequestPolicy(CONFIG)

    def evaluate(self, title, added=(), author="octocat", labels=(), modified=()):
        return self.policy.evaluate(title, author, list(labels), list(added), list(modified))

    def test_required_types_fail_without_a_fragment(self):
        for title_type in ["feat", "fix", "perf", "refactor", "build", "chore"]:
            with self.subTest(title_type=title_type):
                result = self.evaluate(f"{title_type}: change something")
                self.assertFalse(result.ok)
                self.assertEqual(result.rule, "missing-fragment")
                self.assertIn("no-changelog", result.report)

    def test_required_type_passes_with_a_fragment(self):
        result = self.evaluate("feat(ws): add reconnect", added=["changelog.d/664.added.md"])
        self.assertTrue(result.ok)
        self.assertEqual(result.rule, "fragment-added")

    def test_exempt_types_pass_without_a_fragment(self):
        for title_type in ["docs", "test", "ci", "style"]:
            with self.subTest(title_type=title_type):
                result = self.evaluate(f"{title_type}: tidy up")
                self.assertTrue(result.ok)
                self.assertEqual(result.rule, "exempt-type")

    def test_breaking_title_needs_a_breaking_fragment(self):
        missing = self.evaluate("feat!: drop the old API", added=["changelog.d/664.added.md"])
        self.assertFalse(missing.ok)
        self.assertEqual(missing.rule, "breaking-title")
        present = self.evaluate("refactor(core)!: drop the old API", added=["changelog.d/664.breaking.md"])
        self.assertTrue(present.ok)

    def test_breaking_title_applies_to_exempt_types_too(self):
        self.assertFalse(self.evaluate("docs!: rewrite the config reference").ok)

    def test_bots_and_skip_label_pass(self):
        self.assertEqual(self.evaluate("feat: x", author="agent-kernel-ci[bot]").rule, "bot")
        self.assertEqual(self.evaluate("feat: x", labels=["documentation", "no-changelog"]).rule, "label")
        self.assertEqual(self.evaluate("feat!: x", labels=["no-changelog"]).rule, "label")

    def test_invalid_fragment_fails_whatever_the_title_or_author(self):
        for kwargs in [
            {"title": "docs: tidy", "added": ["changelog.d/700.feature.md"]},
            {"title": "feat: x", "added": ["changelog.d/700.feature.md"], "labels": ["no-changelog"]},
            {"title": "feat: x", "added": ["changelog.d/664.added.md"], "modified": ["changelog.d/12.Added.md"]},
            {"title": "chore: x", "added": ["changelog.d/abc.added.md"], "author": "dependabot[bot]"},
        ]:
            with self.subTest(**{k: str(v) for k, v in kwargs.items()}):
                result = self.evaluate(**kwargs)
                self.assertFalse(result.ok)
                self.assertEqual(result.rule, "invalid-fragment")

    def test_only_files_directly_in_the_fragment_directory_count(self):
        result = self.evaluate("feat: x", added=["changelog.d/README.md", "docs/changelog.d/664.added.md", "changelog.d/sub/664.added.md"])
        self.assertFalse(result.ok)
        self.assertEqual(result.rule, "missing-fragment")

    def test_modified_fragment_does_not_satisfy_the_requirement(self):
        result = self.evaluate("fix: x", modified=["changelog.d/664.fixed.md"])
        self.assertEqual(result.rule, "missing-fragment")

    def test_unparsed_title_is_left_to_the_title_check(self):
        result = self.evaluate("Add a thing")
        self.assertTrue(result.ok)
        self.assertEqual(result.rule, "title-unparsed")


class TestReleaseGuard(unittest.TestCase):
    def test_validate(self):
        with TempFragments("664.added.md", "README.md") as root:
            self.assertTrue(ReleaseGuard(FragmentDirectory(root, CONFIG)).validate().ok)
        with TempFragments("664.added.md", "700.feature.md") as root:
            result = ReleaseGuard(FragmentDirectory(root, CONFIG)).validate()
            self.assertFalse(result.ok)
            self.assertIn("700.feature.md", result.report)

    def test_patch_bump_refused_while_breaking_fragment_pending(self):
        with TempFragments("870.breaking.md", "664.added.md") as root:
            guard = ReleaseGuard(FragmentDirectory(root, CONFIG))
            refused = guard.check_bump("patch")
            self.assertFalse(refused.ok)
            self.assertIn("870.breaking.md", refused.report)
            self.assertIn("minor", refused.report)
            self.assertTrue(guard.check_bump("minor").ok)
            self.assertTrue(guard.check_bump("major").ok)

    def test_patch_bump_allowed_without_breaking_fragments(self):
        with TempFragments("664.added.md") as root:
            self.assertTrue(ReleaseGuard(FragmentDirectory(root, CONFIG)).check_bump("patch").ok)


class TestCLI(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)
        shutil.copy(REPO_ROOT / "towncrier.toml", self.root / "towncrier.toml")
        (self.root / "changelog.d").mkdir()
        self.summary = self.root / "summary.md"
        self._env = os.environ.get("GITHUB_STEP_SUMMARY")
        os.environ["GITHUB_STEP_SUMMARY"] = str(self.summary)

    def tearDown(self):
        if self._env is None:
            os.environ.pop("GITHUB_STEP_SUMMARY", None)
        else:
            os.environ["GITHUB_STEP_SUMMARY"] = self._env
        self._dir.cleanup()

    def run_cli(self, *argv: str) -> int:
        return ChangelogCLI(self.root).run(list(argv))

    def test_exit_codes_and_step_summary(self):
        self.assertEqual(self.run_cli("validate"), 0)
        (self.root / "changelog.d" / "870.breaking.md").write_text("Entry.\n", encoding="utf-8")
        self.assertEqual(self.run_cli("check-bump", "--bump", "patch"), 1)
        self.assertEqual(self.run_cli("check-bump", "--bump", "minor"), 0)
        self.assertEqual(self.run_cli("check-pr", "--title", "feat: x", "--author", "octocat"), 1)
        self.assertEqual(
            self.run_cli("check-pr", "--title", "feat: x", "--author", "octocat", "--labels", " documentation , no-changelog "),
            0,
        )
        self.assertEqual(
            self.run_cli("check-pr", "--title", "feat: x", "--author", "octocat", "--added", "changelog.d/1.added.md"),
            0,
        )
        summary = self.summary.read_text(encoding="utf-8")
        self.assertIn("### Changelog version bump: failed", summary)
        self.assertIn("Rule: `label`", summary)


if __name__ == "__main__":
    unittest.main(verbosity=2)
