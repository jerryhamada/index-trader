"""Download and cache price bars from Yahoo.

Yahoo serves about 30 days of 1-minute bars and two years of hourly bars.
Every fetch is merged into the cache in data/, so the 1-minute history keeps
growing past a month as long as a fetch happens at least every few weeks.
"""
import logging
import os
from pathlib import Path

import pandas as pd
import yfinance as yf

TICKERS = ["SPY", "QQQ", "DIA", "GLD"]
DATA_DIR = Path(__file__).parent / "data"
NY = "America/New_York"
COLS = ["Open", "High", "Low", "Close", "Volume"]
SESSION_MIN = 390  # 09:30-16:00
HOURLY = 60  # bar size that is read from the hourly cache instead of 1-minute bars

# interval -> (days of history Yahoo will serve, most days it allows per request)
SOURCES = {"1m": (29, 7), "1h": (729, 729)}

logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # it logs an error for every weekend


def _path(ticker: str, interval: str) -> Path:
    return DATA_DIR / f"{ticker}_{interval}.csv"


def _download(ticker: str, interval: str) -> pd.DataFrame:
    history, per_request = SOURCES[interval]
    end = pd.Timestamp.now(tz="UTC")
    start = end - pd.Timedelta(days=history)
    frames = []
    while start < end:
        stop = min(start + pd.Timedelta(days=per_request), end)
        df = yf.Ticker(ticker).history(
            start=start, end=stop, interval=interval, prepost=False, auto_adjust=False, actions=False
        )
        if not df.empty:
            frames.append(df[COLS])
        start = stop
    if not frames:
        raise RuntimeError(f"Yahoo returned no {interval} data for {ticker}")
    out = pd.concat(frames)
    out.index = out.index.tz_convert("UTC")
    return out


def _read(ticker: str, interval: str) -> pd.DataFrame:
    df = pd.read_csv(_path(ticker, interval), index_col=0)
    df.index = pd.to_datetime(df.index, utc=True)
    return df


def fetch(ticker: str, interval: str = "1m") -> pd.DataFrame:
    """Download the latest bars and merge them into the cached history."""
    df = _download(ticker, interval)
    if _path(ticker, interval).exists():
        df = pd.concat([_read(ticker, interval), df])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    DATA_DIR.mkdir(exist_ok=True)
    tmp = _path(ticker, interval).with_suffix(".tmp")
    df.to_csv(tmp)
    os.replace(tmp, _path(ticker, interval))  # readers never see a half-written file
    return df


def load(ticker: str, bar_min: int = 1, days: int | None = None) -> pd.DataFrame:
    """Regular-session bars in New York time at the given bar size.

    60-minute bars come from the hourly cache; anything else is built from
    1-minute bars. days keeps only the most recent N sessions.
    """
    hourly = bar_min == HOURLY
    df = _read(ticker, "1h" if hourly else "1m").tz_convert(NY).between_time("09:30", "15:59")

    now = pd.Timestamp.now(tz=NY)
    if now.hour < 16:  # today's session is not finished
        df = df[df.index.normalize() < now.normalize()]

    bars = pd.Series(1, index=df.index).groupby(df.index.normalize()).transform("size")
    df = df[bars >= (3 if hourly else 120)]  # drop sessions that are mostly missing

    if days:
        keep = df.index.normalize().unique()[-days:]
        df = df[df.index.normalize().isin(keep)]

    if bar_min not in (1, HOURLY):
        df = (
            df.resample(f"{bar_min}min")
            .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
            .dropna(subset=["Close"])
        )
    return df


def session_minute(df: pd.DataFrame) -> pd.Series:
    """Minutes since 09:30 at the start of each bar."""
    return pd.Series(df.index.hour * 60 + df.index.minute - 570, index=df.index)


if __name__ == "__main__":
    for t in TICKERS:
        for interval in SOURCES:
            d = fetch(t, interval)
            print(f"{t} {interval}: {len(d):,} bars, {d.index[0]:%Y-%m-%d} to {d.index[-1]:%Y-%m-%d}")
