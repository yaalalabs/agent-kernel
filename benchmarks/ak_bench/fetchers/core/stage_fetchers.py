from dataclasses import dataclass, field

from ak_bench.errors import HostRefused
from ak_bench.fetchers.core.info_fetcher import InfoFetcher
from ak_bench.fetchers.core.scaling import ScalingInfoFetcher


@dataclass
class StageFetchers:
    during_step: list[InfoFetcher] = field(default_factory=list)
    cooldown_checks: list[InfoFetcher] = field(default_factory=list)
    after_step: list[InfoFetcher] = field(default_factory=list)
    after_all_steps: list[InfoFetcher] = field(default_factory=list)
    after_teardown: list[InfoFetcher] = field(default_factory=list)

    def all(self) -> list[InfoFetcher]:
        """Every distinct fetcher object, first-seen order."""
        lists = (self.during_step, self.cooldown_checks, self.after_step, self.after_all_steps, self.after_teardown)
        return list({id(f): f for fetchers in lists for f in fetchers}.values())

    def in_step_lists(self, family: type) -> list[InfoFetcher]:
        """Distinct fetchers of this family in during_step, cooldown_checks or after_step, first-seen order."""
        lists = (self.during_step, self.cooldown_checks, self.after_step)
        return list({id(f): f for fetchers in lists for f in fetchers if isinstance(f, family)}.values())

    def validate(self, host: str) -> None:
        for f in self.all():
            if not getattr(f, "name", ""):
                raise HostRefused(f"host '{host}': fetcher {type(f).__name__} has no name")
        for f in self.cooldown_checks:
            if type(f).is_settled is InfoFetcher.is_settled:
                raise HostRefused(f"host '{host}': cooldown_checks fetcher '{f.name}' does not implement is_settled()")
            if isinstance(f, ScalingInfoFetcher) and "running" not in f.count_types:
                raise HostRefused(f"host '{host}': cooldown_checks fetcher '{f.name}' does not give the 'running' count type")
