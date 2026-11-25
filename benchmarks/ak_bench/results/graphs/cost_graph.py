from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

from ak_bench.results.graphs.plots import INK2, SERIES, Plots


class CostReport(Plots):
    """Billed cost of the whole run by service (`<deployment>/graphs/cost-by-service.png`), one panel per cost metric × fetcher
    (two fetchers' costs are never summed)."""

    def draw(self, deployment_dir: Path) -> None:
        if not (deployment_dir / "cost.csv").exists():
            return
        rows = self.read(deployment_dir / "cost.csv")
        self.save(deployment_dir / "graphs" / "cost-by-service.png", lambda: self._cost(rows), "Sum of every billed period in cost.csv, per service.")

    def _cost(self, rows: list[dict[str, str]]) -> Figure:
        usd: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for r in rows:
            usd[f"{r['metric']} ({r['fetcher']})"][r["service"]] += float(r["usd"] or 0)
        metrics = sorted(usd) or [""]
        fig, axes = plt.subplots(
            len(metrics), 1, figsize=(8, 0.6 + max(2.4, 0.35 * max((len(s) for s in usd.values()), default=1)) * len(metrics)), squeeze=False
        )
        for ax, metric in zip(axes[:, 0], metrics, strict=True):
            services = sorted(usd[metric].items(), key=lambda kv: kv[1]) if metric else []
            ax.barh([s for s, _ in services], [v for _, v in services], color=SERIES[0], height=0.6)
            for i, (_, v) in enumerate(services):
                ax.annotate(f"${v:,.2f}", (v, i), xytext=(4, 0), textcoords="offset points", va="center", color=INK2, fontsize=8)
            ax.set_xlabel("USD")
            ax.set_title(f"Billed cost by service ({metric}, total ${sum(v for _, v in services):,.2f})" if metric else "Billed cost by service")
            self.no_data(ax, bool(services))
        return fig
