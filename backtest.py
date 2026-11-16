"""Intraday backtester: next-bar execution, flat at the close, costs per trade."""
import numpy as np
import pandas as pd


def run(df: pd.DataFrame, pos: pd.Series, cost_bps: float, lag: int = 0) -> pd.DataFrame:
    """Per-bar results for a strategy's target positions.

    pos is the position decided at each bar's close; it earns the next bar's
    return. Nothing is held overnight. cost_bps is charged per side (entry and
    exit each pay it). lag delays every decision by that many extra bars, to
    check an edge survives slower execution.
    """
    day = df.index.normalize()
    pos = pos.astype(float).fillna(0.0)
    if lag:
        pos = pos.groupby(day).shift(lag).fillna(0.0)

    d = day.values
    last_bar = np.r_[d[1:] != d[:-1], True]
    pos = pos.mask(last_bar, 0.0)  # flat into the close, so no overnight gap is ever held

    held = pos.shift(1).fillna(0.0)
    gross = held * df["Close"].pct_change().fillna(0.0)
    traded = pos.diff().abs().fillna(pos.abs())
    entry = (pos != 0) & (pos != pos.shift(1))
    trade = entry.cumsum().where(pos != 0).shift(1)  # which trade each held bar belongs to

    return pd.DataFrame(
        {"day": day, "held": held, "gross": gross, "net": gross - traded * cost_bps / 1e4,
         "entry": entry, "trade": trade},
        index=df.index,
    )


def summarize(bt: pd.DataFrame, bar_min: int) -> dict:
    """Headline numbers for a backtest (or any whole-day slice of one)."""
    trades = int(bt["entry"].sum())
    days = bt["day"].nunique()
    out = {"days": days, "trades": trades}
    if trades == 0 or days == 0:
        return out | dict.fromkeys(
            ["trades_day", "hold_min", "win", "gross_bps", "net_bps", "net_pct", "t", "sharpe"], np.nan
        )

    daily_gross = bt.groupby("day")["gross"].sum()
    daily_net = bt.groupby("day")["net"].sum()
    per_trade = bt.groupby("trade")["gross"].sum()

    def ratio(x, scale):
        return x.mean() / x.std() * np.sqrt(scale) if len(x) > 1 and x.std() > 0 else np.nan

    return out | {
        "trades_day": trades / days,
        "hold_min": (bt["held"] != 0).sum() * bar_min / trades,
        "win": (per_trade > 0).mean(),
        "gross_bps": bt["gross"].sum() / trades * 1e4,  # average per trade, before costs
        "net_bps": bt["net"].sum() / trades * 1e4,  # average per trade, after costs
        "net_pct": bt["net"].sum() * 100,
        "t": ratio(daily_gross, len(daily_gross)),  # t-stat of daily gross P&L
        "sharpe": ratio(daily_net, 252),
    }
