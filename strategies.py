"""Intraday strategy library.

Every strategy takes a bar DataFrame and returns the position it wants
(+1 long, -1 short, 0 flat) decided at each bar's close, using only data up to
that close. The backtester applies it to the *next* bar and flattens at the
end of the day.

All of these are trend-following: they go with the move. Trading one in
reverse turns it into the matching mean-reversion strategy, so the scan covers
both directions at once.
"""
import numpy as np
import pandas as pd

from data import SESSION_MIN, session_minute


def _day(df):
    return df.index.normalize()


def _hold(sig: pd.Series, df) -> pd.Series:
    """Keep the last signal until a new one arrives; flat until the day's first."""
    return sig.groupby(_day(df)).ffill().fillna(0.0)


def _blank(df) -> pd.Series:
    return pd.Series(np.nan, index=df.index)


def ema_cross(df, fast: int, slow: int):
    """Long while the fast average is above the slow one, short while below."""
    c = df["Close"]
    return np.sign(c.ewm(span=fast, adjust=False).mean() - c.ewm(span=slow, adjust=False).mean())


def macd(df, fast: int = 12, slow: int = 26, signal: int = 9):
    """Long while the MACD line is above its signal line."""
    c = df["Close"]
    line = c.ewm(span=fast, adjust=False).mean() - c.ewm(span=slow, adjust=False).mean()
    return np.sign(line - line.ewm(span=signal, adjust=False).mean())


def momentum(df, n: int):
    """Long if price is higher than n bars ago, short if lower."""
    return np.sign(df["Close"].pct_change(n)).fillna(0.0)


def donchian(df, n: int):
    """Breakout: long on a close above the prior n-bar high, short below the low."""
    sig = _blank(df)
    sig[df["Close"] > df["High"].rolling(n).max().shift(1)] = 1.0
    sig[df["Close"] < df["Low"].rolling(n).min().shift(1)] = -1.0
    return _hold(sig, df)


def bollinger(df, n: int, k: float = 2.0):
    """Enter when price closes outside the band, exit when it crosses the mean."""
    c = df["Close"]
    mid, sd = c.rolling(n).mean(), c.rolling(n).std()
    side = np.sign(c - mid)
    stretch = (side != side.shift()).cumsum()  # one run on the same side of the mean
    broke = ((c > mid + k * sd) | (c < mid - k * sd)).astype(float)
    active = broke.groupby([_day(df), stretch.values]).cummax()
    return (side * active).fillna(0.0)


def rsi_trend(df, n: int = 14, band: float = 10.0):
    """Long when RSI is above 50+band, short when below 50-band."""
    d = df["Close"].diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rsi = 100 - 100 / (1 + up / down)
    return (rsi > 50 + band).astype(float) - (rsi < 50 - band).astype(float)


def vwap_trend(df, band_bps: float = 0.0):
    """Long above the session's volume-weighted average price, short below."""
    day = _day(df)
    typical = (df["High"] + df["Low"] + df["Close"]) / 3
    vwap = (typical * df["Volume"]).groupby(day).cumsum() / df["Volume"].groupby(day).cumsum()
    sig = _blank(df)
    sig[df["Close"] > vwap * (1 + band_bps / 1e4)] = 1.0
    sig[df["Close"] < vwap * (1 - band_bps / 1e4)] = -1.0
    return _hold(sig, df)


def opening_range(df, range_min: int):
    """Opening range breakout: trade a close outside the first range_min minutes."""
    day, minute = _day(df), session_minute(df)
    in_range = minute < range_min
    high = df["High"].where(in_range).groupby(day).transform("max")
    low = df["Low"].where(in_range).groupby(day).transform("min")
    sig = _blank(df)
    sig[~in_range & (df["Close"] > high)] = 1.0
    sig[~in_range & (df["Close"] < low)] = -1.0
    return _hold(sig, df)


def late_momentum(df, signal_min: int, hold_min: int, bar_min: int):
    """Trade the last hold_min minutes in the direction of the day so far.

    The direction is the move from yesterday's close to signal_min minutes
    after the open.
    """
    day = _day(df)
    c = df["Close"]
    bar_end = (session_minute(df) + bar_min).clip(upper=SESSION_MIN)  # the last hourly bar is short
    prev_close = c.groupby(day).last().shift(1).reindex(day).set_axis(df.index)
    at_signal = c.where(bar_end <= signal_min).groupby(day).transform("last")
    direction = np.sign(at_signal / prev_close - 1)
    in_window = (bar_end >= SESSION_MIN - hold_min) & (bar_end < SESSION_MIN)
    return direction.where(in_window, 0.0).fillna(0.0)


LOOKBACKS = [10, 20, 30, 60, 120, 240, 390]  # minutes


def configs(bar_min: int):
    """Every (strategy, label, function, spec) to test at this bar size.

    Lookbacks are set in minutes so the same idea is compared across bar sizes.
    spec holds the parameters in clock time, so year.py can rebuild the same
    idea on hourly bars.
    """
    out = []

    def bars(minutes):
        return minutes // bar_min if minutes % bar_min == 0 else 0

    for m in LOOKBACKS:
        n = bars(m)
        if n < 2:
            continue
        spec = {"minutes": m}
        out.append(("donchian", f"{m}m", lambda d, n=n: donchian(d, n), spec))
        out.append(("momentum", f"{m}m", lambda d, n=n: momentum(d, n), spec))
        if m <= 120:
            out.append(("ema_cross", f"{m}m/{4 * m}m", lambda d, n=n: ema_cross(d, n, 4 * n), spec))
        if n >= 5:
            out.append(("bollinger", f"{m}m", lambda d, n=n: bollinger(d, n), spec))

    out.append(("macd", "12/26/9 bars", macd, {"bar": bar_min}))
    for band in (10, 20):
        out.append(("rsi_trend", f"50±{band}", lambda d, b=band: rsi_trend(d, 14, b), {"bar": bar_min, "band": band}))
    for band in (0, 5, 10):
        out.append(("vwap_trend", f"band {band}bp", lambda d, b=band: vwap_trend(d, b), {"band": band}))
    for m in (5, 15, 30, 60):
        if bars(m) >= 1:
            out.append(("opening_range", f"first {m}m", lambda d, m=m: opening_range(d, m), {"minutes": m}))
    for sig, hold in ((30, 30), (60, 30), (360, 30), (330, 60)):
        if bars(sig) >= 1 and bars(hold) >= 1:
            label = f"open+{sig}m -> last {hold}m"
            fn = lambda d, s=sig, h=hold: late_momentum(d, s, h, bar_min)
            out.append(("late_momentum", label, fn, {"signal": sig, "hold": hold}))
    return out
