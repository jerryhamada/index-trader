"""Re-test the scan's candidates on a year of hourly bars.

Free 1-minute data only reaches back a month, so each candidate is rebuilt on
hourly bars (the finest Yahoo serves for a year) with the same lookbacks in
clock time. The sessions before the scan window were not used to pick the
candidates, so that part of the year is a fair test of whether an edge lasts.
"""
import numpy as np
import pandas as pd

from backtest import run
from data import HOURLY, SESSION_MIN, load
from strategies import (bollinger, configs, donchian, ema_cross, late_momentum, macd, momentum,
                        opening_range, rsi_trend, vwap_trend)

YEAR_SESSIONS = 252


def hourly(name: str, spec: dict, bar_min: int):
    """(label, function) for the same idea on hourly bars, or None if an hour is too coarse."""
    m = spec.get("minutes", 0)
    n = 7 if m == SESSION_MIN else m // 60  # one session is seven hourly bars
    whole = m == SESSION_MIN or (m >= 60 and m % 60 == 0)

    if name == "donchian" and whole:
        return f"{m}m", lambda d: donchian(d, n)
    if name == "momentum" and whole:
        return f"{m}m", lambda d: momentum(d, n)
    if name == "ema_cross" and whole:
        return f"{m}m/{4 * m}m", lambda d: ema_cross(d, m / 60, 4 * m / 60)
    if name == "bollinger" and whole and n >= 4:
        return f"{m}m", lambda d: bollinger(d, n)
    if name == "macd" and 9 * spec["bar"] >= 60:  # every span must be at least one hourly bar
        fast, slow, signal = (k * spec["bar"] / 60 for k in (12, 26, 9))
        return f"{12 * spec['bar']}m/{26 * spec['bar']}m/{9 * spec['bar']}m", lambda d: macd(d, fast, slow, signal)
    if name == "rsi_trend" and 14 * spec["bar"] >= 120:
        return f"{14 * spec['bar']}m, 50±{spec['band']}", lambda d: rsi_trend(d, 14 * spec["bar"] / 60, spec["band"])
    if name == "vwap_trend":
        return f"band {spec['band']}bp", lambda d: vwap_trend(d, spec["band"])
    if name == "opening_range" and m == 60:
        return "first 60m", lambda d: opening_range(d, 60)
    if name == "late_momentum" and spec["signal"] % 60 == 0 and (SESSION_MIN - spec["hold"]) % 60 == 0:
        label = f"open+{spec['signal']}m -> last {spec['hold']}m"
        return label, lambda d: late_momentum(d, spec["signal"], spec["hold"], HOURLY)
    return None


def better_side_daily(bt: pd.DataFrame, side: str) -> pd.Series:
    """Daily net return trading the given side; reversing flips gross but still pays costs."""
    daily = bt.groupby("day")[["gross", "net"]].sum()
    sign = 1.0 if side == "follow" else -1.0
    return sign * daily["gross"] - (daily["gross"] - daily["net"])


def tstat(daily: pd.Series) -> float:
    return daily.mean() / daily.std() * np.sqrt(len(daily)) if daily.std() > 0 else np.nan


def year_check(res: pd.DataFrame, cost_bps: dict) -> dict:
    """Run every candidate in res on the last year of hourly bars."""
    scan_start = load("SPY", 1).index.normalize()[0]
    specs = {bar: {(n, lab): spec for n, lab, _, spec in configs(bar)} for bar in (1, 5, 15)}

    rows, skipped, seen, months = [], [], set(), []
    for c in res[res["holds"]].itertuples():
        bar = int(c.bar.rstrip("m"))
        mapped = hourly(c.strategy, specs[bar][(c.strategy, c.params)], bar)
        if mapped is None:
            skipped.append(f"{c.ticker} {c.strategy} {c.params} ({c.bar} bars)")
            continue
        label, fn = mapped
        if (c.ticker, c.strategy, label, c.side) in seen:
            continue
        seen.add((c.ticker, c.strategy, label, c.side))

        df = load(c.ticker, HOURLY, YEAR_SESSIONS)
        bt = run(df, fn(df), cost_bps[c.ticker])
        daily = better_side_daily(bt, c.side)
        prior, recent = daily[daily.index < scan_start], daily[daily.index >= scan_start]
        trades = int(bt.loc[bt["day"] < scan_start, "entry"].sum())
        monthly = daily.groupby(daily.index.strftime("%Y-%m")).sum() * 100
        prior_monthly = prior.groupby(prior.index.strftime("%Y-%m")).sum()
        months = list(monthly.index)
        t = tstat(prior)
        opposite = better_side_daily(bt, "reverse" if c.side == "follow" else "follow")
        opposite = opposite[opposite.index < scan_start]
        prior_pct = prior.sum() * 100

        rows.append({
            "ticker": c.ticker, "strategy": c.strategy, "params": label, "side": c.side,
            "src_bar": bar, "src_params": c.params,
            "trades": trades,
            "prior_pct": prior_pct,  # net % over the sessions before the scan window
            "prior_bps": prior.sum() / trades * 1e4 if trades else np.nan,  # net per trade
            "prior_t": t,
            "good_months": int((prior_monthly > 0).sum()),
            "prior_months": len(prior_monthly),
            "opposite_pct": opposite.sum() * 100,  # the other side over the same prior sessions
            "opposite_t": tstat(opposite),
            "recent_pct": recent.sum() * 100,  # the scan window itself, on hourly bars
            "monthly": [float(v) for v in monthly],
            "verdict": "held" if prior_pct > 0 and t >= 2 else "weak" if prior_pct > 0 else "failed",
        })

    rows.sort(key=lambda r: -r["prior_pct"])
    sessions = load("SPY", HOURLY, YEAR_SESSIONS).index.normalize().unique()
    return {
        "start": f"{sessions[0]:%Y-%m-%d}", "end": f"{sessions[-1]:%Y-%m-%d}", "sessions": len(sessions),
        "scan_start": f"{scan_start:%Y-%m-%d}", "prior_sessions": int((sessions < scan_start).sum()),
        "months": months, "rows": rows, "skipped": skipped,
    }
