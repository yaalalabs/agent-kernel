import itertools
import random

import pytest

from ak_bench.load.schedule import BurstSchedule, SteadySchedule


def test_burst_is_one_offset_per_client():
    assert [BurstSchedule().offsets(c) for c in (1, 2, 3)] == [[0.0], [0.0], [0.0]]


def test_steady_next_send_is_previous_scheduled_plus_gap():
    offsets = SteadySchedule(1, 5, 60, random.Random(7)).offsets(1)
    replay, expected, t = random.Random(7), [0.0], 0.0
    while (t := t + replay.uniform(1, 5)) <= 60:
        expected.append(t)
    assert offsets == expected
    assert offsets[0] == 0.0
    assert all(1 <= b - a <= 5 for a, b in itertools.pairwise(offsets))
    assert max(offsets) <= 60


def test_steady_min_equal_max_gives_fixed_interval():
    assert SteadySchedule(1, 1, 5, random.Random()).offsets(1) == pytest.approx([0, 1, 2, 3, 4, 5])


def test_steady_clients_draw_different_gaps():
    schedule = SteadySchedule(1, 5, 60, random.Random(3))
    assert schedule.offsets(1) != schedule.offsets(2)
