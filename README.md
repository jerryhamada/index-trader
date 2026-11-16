# index-trader

Scans intraday trend-following strategies on SPY, QQQ, DIA and GLD, and shows
on a dashboard which ones made money, which lost enough to be worth trading in
reverse, and which of those results look like more than luck.

## Dashboard

**Hosted:** https://jerryhamada.github.io/index-trader/ updates by itself after
each US trading day and works from any device, whether or not this Mac is on.
A GitHub Actions workflow (`.github/workflows/update.yml`) downloads the latest
bars, reruns everything and publishes the page. To update it right away:

```bash
gh workflow run update.yml
```

**Local:** the same dashboard with a Refresh button, served from this Mac.

```bash
./start.sh
```

installs a background service, starts it, and opens http://127.0.0.1:8787. The
service starts again at every login and restarts itself if it stops. Every 3
hours it downloads the latest bars and reruns everything. `./stop.sh` stops it
and removes it from login. While the Mac is asleep or off the local copy does
not run; it catches up when the Mac wakes.

Both copies keep their own cache of bars, so each one's 1-minute history grows
past Yahoo's 30 days on its own. The hosted cache lives in GitHub's Actions
cache, which GitHub can clear; if that happens the scan carries on with the
most recent 30 days.

Local service log: `~/Library/Logs/index-trader.log`

## Command line

```bash
.venv/bin/python scan.py --fetch
```

prints the same results as text. `--days 21` limits the scan to the most
recent 21 sessions.

## What it tests

Nine strategy families, each at several lookbacks, on 1-, 5- and 15-minute
bars (428 tests): EMA crossover, MACD, momentum, Donchian breakout, Bollinger
breakout, RSI trend, VWAP trend, opening range breakout, and late-day
momentum. All of them follow the move, so trading one in reverse is the
matching mean-reversion strategy.

Rules shared by every test:

- A signal is decided at a bar's close and earns the next bar's return.
- Everything is flat by the close. Nothing is held overnight.
- Costs are charged per side: 0.5 bps for SPY and QQQ, 1 bp for DIA and GLD
  (`COST_BPS` in `scan.py`).

## Reading the results

- **Gross / trade** (`gross_bps`): average profit per trade before costs.
  Negative means the signal lost money, so the reverse side won.
- **Net** (`edge_pct`): net % over the scan window, trading the better side.
- **Net w/o best days** (`ex_top_pct`): the same with the best 15% of days
  removed. Near zero or negative means a few big days made the result.
- **First part / Second part**: gross per trade on the better side in the
  first 60% and last 40% of sessions. Both need to beat the cost.
- **1 bar late** (`lag_bps`): gross per trade if every order fills one bar late.
- **t-stat**: below about 2 is not distinguishable from noise, and with
  hundreds of tests a few will pass 2 by luck alone.

Reversing a losing strategy only works if it loses *before* costs. A strategy
that loses only because of costs loses in both directions.

A test is a candidate when it beats costs in both parts of the split, one bar
late, and without its best days.

## One-year check

Free 1-minute data only goes back a month, so each candidate is rebuilt on
hourly bars with the same lookbacks in clock time and run over the last 252
sessions. The sessions before the scan window were not used to pick the
candidates, so they are a fair test of whether an edge lasts. A candidate
"held up" if it made money over those sessions with a t-stat of 2 or more.

Candidates that need bars finer than an hour (a 30-minute lookback, for
example) cannot be tested this way. A proper year of minute data needs a paid
or account-based source.

## Files

- `start.sh`, `stop.sh`: install and remove the background service
- `server.py`: serves the local dashboard and refreshes the data on a schedule
- `build.py`: builds the hosted copy as a static site in `site/`
- `report.py`: the data behind the dashboard, shared by `server.py` and `build.py`
- `.github/workflows/update.yml`: the schedule that rebuilds and publishes the hosted copy
- `dashboard.html`: the dashboard page
- `scan.py`: runs every test; text report; full table in `results/scan.csv`
- `year.py`: the one-year check on hourly bars
- `data.py`: download, cache and load bars
- `strategies.py`: the strategies and the parameter grid
- `backtest.py`: the backtester and its summary numbers
- `efficiency.py`: variance ratio test (does price trend or reverse intraday?)
