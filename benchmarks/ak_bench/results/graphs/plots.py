import os
from collections.abc import Callable, Sequence
from itertools import groupby
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: set before pyplot is imported
import matplotlib.pyplot as plt
import numpy
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter, SymmetricalLogLocator

from ak_bench.fetchers.core.resources import ResourceUsageFetcher
from ak_bench.hosts.host import Host
from ak_bench.results.common.keyed_csv import KeyedCsv
from ak_bench.results.common.percentiles import PERCENTILES
from ak_bench.run.run_log import RunLog

PCTS = [f"p{p}" for p in PERCENTILES]
DOT = {"marker": ".", "ms": 4}  # a value between two empty windows is a point, not a line
INK2, MUTED, AXIS, BAND, SHADE = "#52514e", "#898781", "#c3c2b7", "#cde2fb", "#f0efec"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
BOX_NOTE = "Box = p25 to p75, line in the box = p50, whiskers = p0 and p100, diamond = p99."
STYLE = {
    "figure.facecolor": "#fcfcfb",
    "axes.facecolor": "#fcfcfb",
    "axes.edgecolor": AXIS,
    "axes.labelcolor": INK2,
    "axes.titlesize": 10,
    "axes.titlelocation": "left",
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.color": "#e1e0d9",
    "grid.linewidth": 0.6,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "legend.frameon": False,
    "legend.fontsize": 8,
    "font.size": 9,
}


class Plots:
    """Base of the graph classes: each graph in its own figure, written to a temp file then renamed; a failed graph is a
    run-log ERROR and the others still draw (#786 Graphs drawing rules)."""

    def __init__(self, run_log: RunLog):
        self.run_log = run_log

    def save(self, path: Path, draw: Callable[[], Figure], note: str = "") -> None:
        tmp = path.with_name(path.name + ".tmp")
        try:
            with plt.rc_context(STYLE):
                fig = draw()
                if note:
                    fig.text(0.01, 0.005, note, color=MUTED, fontsize=7, ha="left", va="bottom")
                fig.tight_layout(rect=(0, 0.03 if note else 0, 1, 1))
                path.parent.mkdir(parents=True, exist_ok=True)
                fig.savefig(tmp, format="png", dpi=110)
            os.replace(tmp, path)
        except Exception as e:  # noqa: BLE001 - one bad graph is logged, the others still draw
            kept = "; the previous graph is kept and is out of date" if path.exists() else ""
            self.run_log.error(f"graph {path} failed: {type(e).__name__}: {e}{kept}")
        finally:
            plt.close("all")  # also closes a figure whose draw raised half way
            tmp.unlink(missing_ok=True)

    @staticmethod
    def read(path: Path) -> list[dict[str, str]]:
        return KeyedCsv(path, [], []).read()

    @staticmethod
    def values(rows: Sequence[dict[str, str]], column: str) -> numpy.ndarray:
        """A column as floats; an empty or missing cell is NaN, so lines and bands break there."""
        return numpy.array([float(r[column]) if r.get(column) else numpy.nan for r in rows], dtype=float)

    @staticmethod
    def has_data(*series: numpy.ndarray) -> bool:
        return any(numpy.isfinite(s).any() for s in series if len(s))

    @staticmethod
    def no_data(ax: Axes, has_data: bool) -> None:
        """A panel with nothing to show keeps its axes and title and says so, never skipped."""
        if not has_data:
            ax.text(0.5, 0.5, "no data", transform=ax.transAxes, ha="center", va="center", color=MUTED)

    @staticmethod
    def seconds_axis(ax: Axes) -> None:
        """symlog, not log: a duration of 0 or below (client / server clock skew) stays on the graph."""
        ax.set_yscale("symlog", linthresh=1e-3)
        ax.autoscale_view(scalex=False)  # margins again in symlog space; the linear ones leave the top value on the edge
        lo, hi = ax.get_ylim()
        narrow = lo * hi > 0 and max(abs(lo), abs(hi)) < 10 * min(abs(lo), abs(hi))
        # ticks at 1, 2, 5 per decade, every digit when the view is under a decade (0.2-0.5 s), so it is never unlabelled
        ax.yaxis.set_major_locator(SymmetricalLogLocator(base=10, linthresh=1e-3, subs=range(1, 10) if narrow else [1, 2, 5]))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g} s" if v == 0 or abs(v) >= 1 else f"{v * 1000:g} ms"))

    @staticmethod
    def bands(ax: Axes, x: Sequence[float], p: dict[str, numpy.ndarray], color: str = SERIES[0], label: str = "") -> None:
        """p0-p100 light band, p25-p75 dark band, p50 line, dashed p99 line."""
        prefix = f"{label} " if label else ""
        ax.fill_between(x, p["p0"], p["p100"], color=BAND, alpha=0.7, linewidth=0, label=f"{prefix}p0 → p100")
        ax.fill_between(x, p["p25"], p["p75"], color=color, alpha=0.3, linewidth=0, label=f"{prefix}p25 → p75")
        ax.plot(x, p["p50"], color=color, lw=1.5, label=f"{prefix}p50", **DOT)
        ax.plot(x, p["p99"], color=color, lw=1, ls="--", label=f"{prefix}p99")

    @staticmethod
    def boxes(ax: Axes, labels: list[str], pcts: list[dict[str, float | None]]) -> None:
        """One box per category, whiskers at p0 / p100 (whis=(0, 100)), a p99 diamond; an empty category is left blank."""
        for i, p in enumerate(pcts):
            if p["p50"] is None:
                continue
            ax.vlines(i, p["p0"], p["p100"], color=INK2, lw=1)
            ax.hlines([p["p0"], p["p100"]], i - 0.15, i + 0.15, color=INK2, lw=1)
            ax.add_patch(Rectangle((i - 0.3, p["p25"]), 0.6, p["p75"] - p["p25"], facecolor=BAND, edgecolor=SERIES[0], lw=1.2))
            ax.hlines(p["p50"], i - 0.3, i + 0.3, color=SERIES[0], lw=2.5)
            ax.plot(i, p["p99"], marker="D", ms=4, color=SERIES[0], lw=0)
        ax.set_xticks(range(len(labels)), labels, rotation=40, ha="right", fontsize=7)
        ax.set_xlim(-0.5, max(len(labels), 1) - 0.5)
        Plots.no_data(ax, any(p["p50"] is not None for p in pcts))

    @staticmethod
    def shade_parts(axes: Sequence[Axes], x: numpy.ndarray, parts: list[str]) -> None:
        """Shades `before` and `cooldown` windows and names each part above the first panel."""
        if not len(x):
            return
        width = x[1] - x[0] if len(x) > 1 else 1.0
        i = 0
        for part, run in groupby(parts):
            n = len(list(run))
            start, end = x[i], x[i + n - 1] + width
            for ax in axes:
                if part != "load":
                    ax.axvspan(start, end, color=SHADE, zorder=0, lw=0)
            axes[0].annotate(part, ((start + end) / 2, 1.02), xycoords=("data", "axes fraction"), ha="center", color=MUTED, fontsize=8)
            i += n

    def resource_grid(self, tiers: list[str], host: Host, x: Sequence[float], column: Callable[[str], numpy.ndarray]) -> tuple[Figure, numpy.ndarray]:
        """One row of panels per tier, one column per metric; `value` stats as percentile bands, min / avg / max as lines."""
        metrics: dict[str, list[tuple[str, str]]] = {}
        for f in host.fetchers.in_step_lists(ResourceUsageFetcher):
            for metric, stat in sorted(f.metrics):
                metrics.setdefault(metric, []).append((stat, f.name))
        tiers = tiers or [""]
        # at least 03-timeline's width, so a one-panel grid fits its titles and lines up with it
        width = max(5 * len(metrics), 9)
        fig, axes = plt.subplots(len(tiers), max(len(metrics), 1), figsize=(width, 2.4 * len(tiers) + 0.6), squeeze=False)
        for row, tier in zip(axes, tiers, strict=True):
            row[0].set_title(f"tier: {tier}" if tier else "no tiers", color=INK2, pad=14)  # room for the step-part names
            for ax, (metric, series) in zip(row, metrics.items(), strict=False):
                drawn = []
                for i, (stat, fetcher) in enumerate(series):
                    color = SERIES[i % len(SERIES)]
                    if stat == "value":
                        p = {pct: column(f"{tier}.{metric}.{pct}.{fetcher}") for pct in PCTS}
                        self.bands(ax, x, p, color, fetcher)
                        drawn += p.values()
                    else:
                        values = column(f"{tier}.{metric}.{stat}.{fetcher}")
                        ax.plot(x, values, color=color, label=f"{stat} ({fetcher})", **DOT)
                        drawn.append(values)
                ax.set_ylabel(metric)
                self.no_data(ax, self.has_data(*drawn))
                if self.has_data(*drawn):
                    ax.legend(loc="upper right", ncol=2)
            if not metrics:
                self.no_data(row[0], False)
        return fig, axes
