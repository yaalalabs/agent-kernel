import random


class BurstSchedule:
    """One request per client, all at the start."""

    def offsets(self, client: int) -> list[float]:
        return [0.0]


class SteadySchedule:
    """Each client sends at 0, then every rng.uniform(min_s, max_s) after its previous scheduled send, up to load_time_s."""

    def __init__(self, min_s: float, max_s: float, load_time_s: float, rng: random.Random):
        self.min_s = min_s
        self.max_s = max_s
        self.load_time_s = load_time_s
        self.rng = rng

    def offsets(self, client: int) -> list[float]:
        t, out = 0.0, [0.0]
        while True:
            t += self.rng.uniform(self.min_s, self.max_s)
            if t > self.load_time_s:
                return out
            out.append(t)
