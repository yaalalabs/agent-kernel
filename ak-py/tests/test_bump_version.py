import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bump_version import bump_version

TEST_CASES = [
    ("0.1.0a1", "patch", "alpha", True, "0.1.0a2"),  # Patch bump with alpha
    ("0.1.1a1", "patch", "alpha", True, "0.1.1a2"),  # Another patch with alpha
    ("0.1.1a1", "minor", "alpha", True, "0.2.0a1"),  # Minor bump with alpha
    ("0.2.0a1", "minor", "alpha", True, "0.2.0a2"),  # Minor bump with already existing alpha
    ("0.2.0a1", "major", "alpha", True, "1.0.0a1"),  # Major bump with already existing alpha
    ("0.1.0", "patch", "alpha", True, "0.1.1a1"),  # First alpha from stable
    ("0.1.0a1", "patch", "", True, "0.1.0"),  # Stable patch release from alpha
    ("0.2.0b2", "patch", "", True, "0.2.0"),  # Stable patch release from beta
    ("2.0.0b6", "major", "", True, "2.0.0"),  # Stable major release from beta
    ("2.4.0b7", "minor", "", True, "2.4.0"),  # Stable minor release from beta
    ("4.5.6", "major", "", True, "5.0.0"),  # Stable major release from stable
    ("4.5.6", "minor", "", True, "4.6.0"),  # Stable minor release from stable
    ("4.5.6", "patch", "", True, "4.5.7"),  # Stable patch release from stable
    ("0.1.0", "minor", "beta", True, "0.2.0b1"),  # Minor bump with beta
    ("0.1.0", "major", "", True, "1.0.0"),  # Major bump stable
    ("1.0.0", "major", "beta", True, "2.0.0b1"),  # Major bump beta
    ("2.0.0b1", "major", "beta", True, "2.0.0b2"),  # Another major bump beta
    ("3.2.0b1", "minor", "beta", True, "3.2.0b2"),  # Another minor bump beta
    ("0.2.0b1", "minor", "beta", True, "0.2.0b2"),  # Another minor with beta
    ("0.2.0a1", "minor", "beta", True, "0.2.0a2"),  # Another minor with alpha
]


@pytest.mark.parametrize("current,bump,pre,auto,expected", TEST_CASES)
def test_bump_version_cases(current, bump, pre, auto, expected):
    pre_arg = pre if pre else Nonegg
    result = bump_version(current, bump, pre_arg, auto_increment_prerelease=auto)
    assert result == expected
