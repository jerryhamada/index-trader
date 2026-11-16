"""Run every strategy on every ticker and bar size, then report what holds up.

    python scan.py            # scan the cached data
    python scan.py --fetch    # download the latest data first
    python scan.py --days 21  # only the most recent 21 sessions
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import run, summarize
from data import SOURCES, TICKERS, fetch, load
from efficiency import variance_ratio
from strategies import configs
from year import year_check

COST_BPS = {"SPY": 0.5, "QQQ": 0.5, "DIA": 1.0, "GLD": 1.0}  # per side; a round trip pays twice
BAR_SIZES = [1, 5, 15]  # minutes
HORIZONS = [5, 15, 30, 60]  # minutes, for the variance ratio
FIRST_PART = 0.6  # share of sessions in the first part of the split
MIN_TRADES = 15
TOP_DAYS = 0.15  # an edge must survive losing this share of its best days
RESULTS = Path(__file__).parent / "results"


def scan(days: int | None = None) -> pd.DataFrame:
    rows = []
    for ticker in TICKERS:
        cost = COST_BPS[ticker]
        for bar_min in BAR_SIZES:
            df = load(ticker, bar_min, days)
            sessions = df.index.normalize().unique()
            cut = sessions[int(len(sessions) * FIRST_PART)]
            for name, label, fn, _ in configs(bar_min):
                pos = fn(df)
                bt = run(df, pos, cost)
                full = summarize(bt, bar_min)

                # A losing strategy is only worth reversing if it loses *before*
                # costs: reversing flips the gross result but still pays the costs.
                sign = -1.0 if full["gross_bps"] < 0 else 1.0
                daily = bt.groupby("day")[["gross", "net"]].sum()
                best_way = sign * daily["gross"] - (daily["gross"] - daily["net"])  # daily net, better direction
                top = best_way.nlargest(max(2, round(len(best_way) * TOP_DAYS))).sum()
                rows.append(
                    {"ticker": ticker, "bar": f"{bar_min}m", "strategy": name, "params": label}
                    | full
                    | {
                        "side": "follow" if sign > 0 else "reverse",
                        "cost_bps": 2 * cost,
                        "edge_pct": best_way.sum() * 100,  # net % over the test, better direction
                        "ex_top_pct": (best_way.sum() - top) * 100,  # same, without its best days
                        "win_days": (best_way > 0).mean(),
                        "first_bps": sign * summarize(bt[bt["day"] < cut], bar_min)["gross_bps"],
                        "second_bps": sign * summarize(bt[bt["day"] >= cut], bar_min)["gross_bps"],
                        "lag_bps": sign * summarize(run(df, pos, cost, lag=1), bar_min)["gross_bps"],
                    }
                )
    res = pd.DataFrame(rows)
    res["edge_bps"] = res["gross_bps"].abs() - res["cost_bps"]  # net per trade, better direction
    res["holds"] = (
        (res["trades"] >= MIN_TRADES)
        & (res["first_bps"] > res["cost_bps"])
        & (res["second_bps"] > res["cost_bps"])
        & (res["lag_bps"] > res["cost_bps"])
        & (res["ex_top_pct"] > 0)
    )
    return res


def overview(res: pd.DataFrame, days: int | None = None) -> dict:
    """The headline numbers behind the report and the dashboard."""
    sessions = load("SPY", 1, days).index.normalize().unique()
    n_first = int(len(sessions) * FIRST_PART)
    ok = res[res["trades"] >= MIN_TRADES]
    follow = np.where(ok["side"] == "follow", 1, -1)  # undo the better-side flip
    pivot = ok.pivot_table(index="strategy", columns="ticker", values="gross_bps", aggfunc="mean")
    return {
        "sessions": len(sessions), "start": f"{sessions[0]:%Y-%m-%d}", "end": f"{sessions[-1]:%Y-%m-%d}",
        "n_first": n_first, "n_second": len(sessions) - n_first,
        "tests": len(res), "candidates": int(res["holds"].sum()),
        "min_trades": MIN_TRADES, "top_days": TOP_DAYS, "tickers": TICKERS, "horizons": HORIZONS,
        "luck": {
            "tests": len(ok),
            "significant": int((ok["t"].abs() > 2).sum()),
            "by_chance": 0.0455 * len(ok),
            "agree": float((ok["second_bps"] * ok["first_bps"] > 0).mean()),
            "rank_corr": float((follow * ok["first_bps"]).rank().corr((follow * ok["second_bps"]).rank())),
        },
        # ticker -> one (variance ratio, z-score) per horizon
        "efficiency": {t: [variance_ratio(load(t, 1, days)["Close"], q) for q in HORIZONS] for t in TICKERS},
        # strategy -> average gross bps per trade, per ticker
        "pivot": {s: [float(pivot.loc[s].get(t, np.nan)) for t in TICKERS] for s in pivot.index},
    }


def show(df: pd.DataFrame, cols: list[str]) -> None:
    print(df[cols].to_string(index=False, float_format=lambda v: f"{v:,.2f}") if len(df) else "  (none)")


def report(res: pd.DataFrame, ov: dict, yr: dict | None) -> None:
    print(f"\nDATA  {ov['sessions']} sessions, {ov['start']} to {ov['end']}"
          f"  (split: first {ov['n_first']}, last {ov['n_second']})")

    print("\nTREND OR REVERSAL?  variance ratio (z-score) by horizon, from 1-minute returns")
    print("  above 1 = moves tend to continue, below 1 = moves tend to reverse; |z| > 2 is unlikely to be chance")
    print(pd.DataFrame({t: [f"{vr:.2f} ({z:+.1f})" for vr, z in v] for t, v in ov["efficiency"].items()},
                       index=[f"{q}m" for q in HORIZONS]).T.to_string())

    luck = ov["luck"]
    print(f"\nLUCK CHECK  {luck['tests']} tests with at least {MIN_TRADES} trades")
    print(f"  |t| > 2 on daily gross P&L: {luck['significant']}  (pure luck would give about {luck['by_chance']:.0f})")
    print(f"  same sign in both parts of the split: {luck['agree']:.0%}  (coin flip = 50%)")
    print(f"  rank correlation, first part vs second part: {luck['rank_corr']:+.2f}  (0 = nothing carries over)")

    print("\nAVERAGE GROSS EDGE PER TRADE (bps) by strategy and ticker, all bar sizes")
    print("  positive = following the signal made money before costs, negative = reversing it did")
    print(pd.DataFrame(ov["pivot"], index=TICKERS).T.to_string(float_format=lambda v: f"{v:+.2f}"))

    ok = res[res["trades"] >= MIN_TRADES]
    cols = ["ticker", "bar", "strategy", "params", "side", "trades", "hold_min", "gross_bps", "cost_bps",
            "edge_pct", "ex_top_pct", "win_days", "t", "first_bps", "second_bps", "lag_bps"]
    print("\nHOW TO READ  gross_bps = average per trade before costs (negative = the signal lost, so reverse it)")
    print("  edge_pct = net % over the test trading the better side; ex_top_pct = the same without its best days")
    print("  first_bps / second_bps / lag_bps = gross per trade on the better side, in each part of the split")
    print("  and with a 1-bar execution delay; all three need to beat cost_bps")
    for side, title in (("follow", "FOLLOWING the signal"), ("reverse", "REVERSING the signal")):
        print(f"\nTOP 10 {title}, by net % over the test")
        show(ok[ok["side"] == side].nlargest(10, "edge_pct"), cols)

    held = res[res["holds"]].sort_values("ex_top_pct", ascending=False)
    print(f"\nCANDIDATES  {len(held)} beat costs in both parts of the split, with a 1-bar delay, and without")
    print(f"  their best {TOP_DAYS:.0%} of days. Top 15 by net % without best days:")
    show(held.head(15), cols)

    if yr:
        print(f"\nONE-YEAR CHECK  candidates rebuilt on hourly bars, {yr['start']} to {yr['end']}")
        print(f"  prior_* covers the {yr['prior_sessions']} sessions before {yr['scan_start']}, which were not used to pick them")
        show(pd.DataFrame(yr["rows"]), ["ticker", "strategy", "params", "side", "trades", "prior_pct", "prior_bps",
                                        "prior_t", "good_months", "prior_months", "recent_pct", "verdict"])
        if yr["skipped"]:
            print(f"  {len(yr['skipped'])} candidates need bars finer than an hour and could not be tested")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fetch", action="store_true", help="download the latest data before scanning")
    ap.add_argument("--days", type=int, help="use only the most recent N sessions")
    args = ap.parse_args()

    if args.fetch:
        for t in TICKERS:
            for interval in SOURCES:
                fetch(t, interval)
    res = scan(args.days)
    RESULTS.mkdir(exist_ok=True)
    res.to_csv(RESULTS / "scan.csv", index=False)
    try:
        yr = year_check(res, COST_BPS)
    except FileNotFoundError:
        yr = None
        print("No hourly data cached, so the one-year check was skipped. Run with --fetch.")
    report(res, overview(res, args.days), yr)
    print(f"\nAll {len(res)} results saved to {RESULTS / 'scan.csv'}")


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    main()
