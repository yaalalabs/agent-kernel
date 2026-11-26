import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy
from matplotlib.figure import Figure

from ak_bench.config import TestType
from ak_bench.fetchers.core.scaling import ScalingInfoFetcher
from ak_bench.fetchers.core.transport import TransportCollector
from ak_bench.hosts.host import Deployment, Host
from ak_bench.results.common.keyed_csv import KeyedCsv
from ak_bench.results.common.percentiles import percentiles
from ak_bench.results.csv.per_request import DURATION_STAGES
from ak_bench.results.graphs.plots import AXIS, BOX_NOTE, DOT, INK2, MUTED, PCTS, SERIES, Plots


class StepPlots(Plots):
    """The graphs of one step (`step-<N>/graphs/`), from its per-request.csv, per-time-window.csv and step-metadata.json."""

    def draw(self, step_dir: Path, test_type: str, host: Host, deployment: Deployment) -> None:
        requests = self.read(step_dir / "per-request.csv")
        windows = self.read(step_dir / "per-time-window.csv")
        graphs, name = step_dir / "graphs", f"{test_type}, {step_dir.name}"
        self.save(graphs / "01-stage-times.png", lambda: self._stage_times(requests, name), BOX_NOTE)
        self.save(
            graphs / "02-stage-breakdown.png",
            lambda: self._stage_breakdown(requests, name),
            "Fastest / slowest: the completed request with the lowest / highest latency; average: each stage's mean.",
        )
        timeline = self._steady_timeline if test_type == TestType.STEADY else self._burst_timeline
        self.save(graphs / "03-timeline.png", lambda: timeline(requests, windows, host, deployment, name), "Read top to bottom at the same moment.")
        if test_type == TestType.STEADY:
            self.save(
                graphs / "04-every-request.png",
                lambda: self._every_request(step_dir, requests, windows, name),
                "Timed-out requests are drawn on the timeout line.",
            )
        self.save(
            graphs / "05-resource-usage.png", lambda: self._resource_usage(windows, host, deployment, name), "Same time axis as 03-timeline.png."
        )

    @staticmethod
    def stages(requests: list[dict[str, str]]) -> list[str]:
        """The duration stages with at least one value: the driver's chain, without the stages it never passes."""
        return [s for s in DURATION_STAGES if any(r.get(f"{s}_s") for r in requests)]

    def _stage_times(self, requests: list[dict[str, str]], name: str) -> Figure:
        fig, ax = plt.subplots(figsize=(9, 5))
        stages = self.stages(requests)
        self.boxes(ax, stages, [percentiles([float(r[f"{s}_s"]) for r in requests if r[f"{s}_s"]]) for s in stages])
        self.seconds_axis(ax)
        ax.set_ylabel("time from the previous point")
        ax.set_title(f"Stage times ({name}, {len(requests)} request{'s' * (len(requests) != 1)})")
        return fig

    def _stage_breakdown(self, requests: list[dict[str, str]], name: str) -> Figure:
        fig, ax = plt.subplots(figsize=(10, 4.2))
        stages = self.stages(requests)
        done = [r for r in requests if r["status"] == "ok" and r["latency_s"]]
        ax.set_title(f"Where the time goes, by TraceStage ({name})")
        self.no_data(ax, bool(done and stages))
        if done and stages:
            durations = numpy.array([[float(r[f"{s}_s"]) if r[f"{s}_s"] else numpy.nan for s in stages] for r in done])
            latency = [float(r["latency_s"]) for r in done]
            rows = numpy.nan_to_num(
                numpy.vstack(
                    [
                        durations[numpy.argmin(latency)],
                        numpy.nansum(durations, axis=0) / numpy.maximum(numpy.isfinite(durations).sum(axis=0), 1),
                        durations[numpy.argmax(latency)],
                    ]
                )
            )
            left = numpy.zeros(3)
            for j, stage in enumerate(stages):
                color = AXIS if stage == stages[-1] else SERIES[j % len(SERIES)]
                ax.barh([2, 1, 0], rows[:, j], left=left, color=color, height=0.6, label=stage)
                left += rows[:, j]
            ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=4)
        ax.set_yticks([2, 1, 0], ["fastest request", "average request", "slowest request"])
        ax.set_xlabel("seconds")
        return fig

    def _time_axis(self, windows: list[dict[str, str]]) -> numpy.ndarray:
        """Window starts in seconds from the step start (the first window's start)."""
        starts = [KeyedCsv.parse_ts(w["window_start"]) for w in windows]
        return numpy.array([(t - starts[0]).total_seconds() for t in starts]) if starts else numpy.array([])

    def _count_panels(self, axes, windows, x, host: Host, deployment: Deployment) -> None:
        """One worker panel per tier: each count type of each scaling fetcher as its own line."""
        scaling = [(ct, f.name) for f in host.fetchers.in_step_lists(ScalingInfoFetcher) for ct in sorted(f.count_types)]
        for ax, tier in zip(axes, list(deployment.resources) or [""], strict=True):
            drawn = [self.values(windows, f"{tier}.{ct}.{fetcher}") for ct, fetcher in scaling]
            for i, ((ct, fetcher), values) in enumerate(zip(scaling, drawn, strict=True)):
                ax.step(x, values, where="post", color=SERIES[i % len(SERIES)], label=f"{ct} ({fetcher})", **DOT)
            ax.set_title(f"tier: {tier}" if tier else "no tiers", color=INK2)
            ax.set_ylabel("workers")
            self.no_data(ax, self.has_data(*drawn))
            if self.has_data(*drawn):
                ax.legend(loc="upper right", ncol=2)

    def _steady_timeline(self, requests, windows, host: Host, deployment: Deployment, name: str) -> Figure:
        queues, tiers = list(deployment.queues), list(deployment.resources) or [""]
        fig, axes = plt.subplots(2 + len(queues) + len(tiers), 1, figsize=(9, 2 * (2 + len(queues) + len(tiers))), sharex=True, squeeze=False)
        axes = axes[:, 0]
        x = self._time_axis(windows)
        tx, rx = self.values(windows, "tx_per_s"), self.values(windows, "rx_per_s")
        axes[0].plot(x, tx, color=SERIES[0], label="Tx (sent/s)", **DOT)
        axes[0].plot(x, rx, color=SERIES[1], label="Rx (received/s)", **DOT)
        axes[0].set_ylabel("requests / s")
        self.no_data(axes[0], self.has_data(tx, rx))
        if self.has_data(tx, rx):
            axes[0].legend(loc="upper right", ncol=2)
        latency = {p: self.values(windows, f"latency_{p}") for p in PCTS}
        self.bands(axes[1], x, latency)
        self.seconds_axis(axes[1])
        axes[1].set_ylabel("latency per window")
        self.no_data(axes[1], self.has_data(*latency.values()))
        if self.has_data(*latency.values()):
            axes[1].legend(loc="upper right", ncol=4)
        transports = [f.name for f in host.fetchers.in_step_lists(TransportCollector)]
        for ax, queue in zip(axes[2 : 2 + len(queues)], queues, strict=True):
            drawn = []
            for i, (fetcher, kind) in enumerate((f, k) for f in transports for k in ("waiting", "in_flight")):
                values = self.values(windows, f"{queue}.{kind}.{fetcher}")
                ax.plot(x, values, color=SERIES[i % len(SERIES)], label=f"{kind} ({fetcher})", **DOT)
                drawn.append(values)
            ax.set_ylabel(f"{queue} queue\n(messages)")
            self.no_data(ax, self.has_data(*drawn))
            if self.has_data(*drawn):
                ax.legend(loc="upper right", ncol=2)
        self._count_panels(axes[2 + len(queues) :], windows, x, host, deployment)
        self.shade_parts(axes, x, [w["step_part"] for w in windows])
        axes[-1].set_xlabel("time (s from step start)")
        fig.suptitle(f"One step from start to end ({name})", x=0.01, ha="left", fontweight="bold")
        return fig

    def _burst_timeline(self, requests, windows, host: Host, deployment: Deployment, name: str) -> Figure:
        tiers = list(deployment.resources) or [""]
        fig, axes = plt.subplots(1 + len(tiers), 1, figsize=(9, 2.2 * (1 + len(tiers))), sharex=True, squeeze=False)
        axes = axes[:, 0]
        x = self._time_axis(windows)
        start = KeyedCsv.parse_ts(windows[0]["window_start"]) if windows else None
        done = sorted((KeyedCsv.parse_ts(r["complete"]) - start).total_seconds() for r in requests if start and r["status"] == "ok" and r["complete"])
        axes[0].step([0.0, *done], range(len(done) + 1), where="post", color=SERIES[0])
        axes[0].axhline(len(requests), color=MUTED, lw=1, ls=":")
        timeouts = sum(r["status"] == "timeout" for r in requests)
        axes[0].set_title(f"N = {len(requests)} sent; {len(done)} answered, {timeouts} timed out", color=INK2)
        axes[0].set_ylabel("responses\nreceived so far")
        self.no_data(axes[0], bool(requests))
        self._count_panels(axes[1:], windows, x, host, deployment)
        self.shade_parts(axes, x, [w["step_part"] for w in windows])
        axes[-1].set_xlabel("time (s from step start)")
        fig.suptitle(f"One burst step ({name})", x=0.01, ha="left", fontweight="bold")
        return fig

    def _every_request(self, step_dir: Path, requests, windows, name: str) -> Figure:
        meta = json.loads((step_dir / "step-metadata.json").read_text()) if (step_dir / "step-metadata.json").exists() else {}
        timeout = meta.get("client_timeout_s")
        fig, ax = plt.subplots(figsize=(9, 4.8))
        x = self._time_axis(windows)
        start = KeyedCsv.parse_ts(windows[0]["window_start"]) if windows else None
        ok = [r for r in requests if start and r["sent"] and r["latency_s"]]
        timed_out = [r for r in requests if start and r["sent"] and r["status"] == "timeout"]
        sent = lambda rows: [(KeyedCsv.parse_ts(r["sent"]) - start).total_seconds() for r in rows]
        ax.scatter(sent(ok), [float(r["latency_s"]) for r in ok], s=8, color=SERIES[0], alpha=0.6, linewidths=0, label="one request")
        if timeout is not None:
            ax.scatter(sent(timed_out), [timeout] * len(timed_out), s=28, marker="x", color=SERIES[7], label=f"timed out ({len(timed_out)})")
            if timed_out:  # drawn only when used: it would stretch the axis far above every answered request
                ax.axhline(timeout, color=MUTED, lw=1, ls=":")
        width = x[1] - x[0] if len(x) > 1 else 0.0
        latency = {p: self.values(windows, f"latency_{p}") for p in PCTS}
        self.bands(ax, x + width / 2, latency)
        self.seconds_axis(ax)
        ax.set_xlabel("send time (s from step start)")
        ax.set_ylabel("end-to-end latency")
        ax.set_title(f"Every request in one step ({name})")
        self.no_data(ax, bool(ok or timed_out))
        ax.legend(loc="upper right", ncol=3, markerscale=2)
        return fig

    def _resource_usage(self, windows, host: Host, deployment: Deployment, name: str) -> Figure:
        x = self._time_axis(windows)
        fig, axes = self.resource_grid(list(deployment.resources), host, x, lambda column: self.values(windows, column))
        self.shade_parts(list(axes.flat), x, [w["step_part"] for w in windows])
        for ax in axes[-1]:
            ax.set_xlabel("time (s from step start)")
        fig.suptitle(f"Resource usage over one step ({name})", x=0.01, ha="left", fontweight="bold")
        return fig
