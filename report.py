"""Everything the dashboard shows, as plain JSON-ready data.

Shared by server.py (the local dashboard) and build.py (the hosted static site).
"""
import math
import time
from functools import lru_cache

import numpy as np
import pandas as pd

from backtest import run
from data import HOURLY, SOURCES, TICKERS, fetch, load
from scan import COST_BPS, RESULTS, overview, scan
from strategies import configs
from year import YEAR_SESSIONS, hourly, year_check

MAX_POINTS = 600  # per line on the detail chart

bars = lru_cache(maxsize=32)(load)  # detail charts reuse the same few frames; cleared on every fetch


def plain(obj):
    """Plain JSON types: numpy scalars to Python, NaN and infinity to None."""
    if isinstance(obj, dict):
        return {str(k): plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [plain(v) for v in obj]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return float(obj) if math.isfinite(obj) else None
    return obj


def fetch_all() -> list[str]:
    """Download the latest bars for every ticker; returns what failed (offline, or Yahoo refused)."""
    failed = []
    for ticker in TICKERS:
        for interval in SOURCES:
            try:
                fetch(ticker, interval)
            except Exception as e:
                failed.append(f"{ticker} {interval}: {e}")
    bars.cache_clear()
    return failed


def compute() -> dict:
    """Run the scan and the one-year check on the cached bars."""
    res = scan()
    RESULTS.mkdir(exist_ok=True)
    res.to_csv(RESULTS / "scan.csv", index=False)
    return plain({
        "overview": overview(res),
        "results": res.to_dict(orient="records"),
        "year": year_check(res, COST_BPS),
        "refreshed": time.time(),
    })


def detail(q: dict, scan_start: str | None = None) -> dict:
    """Cumulative and daily net return for one test, on both sides of the signal.

    q names the test: ticker, bar, strategy, params, and year=1 for its
    hourly one-year version.
    """
    ticker, bar, name, label = q["ticker"], int(q["bar"]), q["strategy"], q["params"]
    year = str(q.get("year", "")) == "1"
    fn, spec = {(n, lab): (f, s) for n, lab, f, s in configs(bar)}[(name, label)]
    if year:
        _, fn = hourly(name, spec, bar)
    df = bars(ticker, HOURLY, YEAR_SESSIONS) if year else bars(ticker, bar)
    bt = run(df, fn(df), COST_BPS[ticker])

    cost = bt["gross"] - bt["net"]
    sides = pd.DataFrame({"follow": bt["net"], "reverse": -bt["gross"] - cost}) * 100
    daily = sides.groupby(bt["day"]).sum()
    if year:
        curve = daily.cumsum()
        stamps = [f"{d:%Y-%m-%d}" for d in curve.index]
    else:
        curve = sides.cumsum().iloc[:: max(1, len(sides) // MAX_POINTS)]
        stamps = [f"{d:%Y-%m-%d %H:%M}" for d in curve.index]
    return plain({
        "t": stamps,
        "follow": curve["follow"].round(3).tolist(),
        "reverse": curve["reverse"].round(3).tolist(),
        "days": [f"{d:%Y-%m-%d}" for d in daily.index],
        "daily_follow": daily["follow"].round(3).tolist(),
        "daily_reverse": daily["reverse"].round(3).tolist(),
        "scan_start": scan_start if year else None,
    })
