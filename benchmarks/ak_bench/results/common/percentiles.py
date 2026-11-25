from collections.abc import Sequence

import numpy

PERCENTILES = (0, 25, 50, 75, 99, 100)
METHOD = "linear"


def percentiles(values: Sequence[float]) -> dict[str, float | None]:
    """{"p0": ..., "p100": ...} over the values; all None for an empty input."""
    if not values:
        return {f"p{p}": None for p in PERCENTILES}
    return {f"p{p}": float(v) for p, v in zip(PERCENTILES, numpy.percentile(values, PERCENTILES, method=METHOD), strict=True)}
