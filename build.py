"""Build the dashboard as a static site in site/, for hosting on GitHub Pages.

    python build.py             # download the latest bars, then build
    python build.py --no-fetch  # build from the cached bars only

The hosted page has no server behind it, so every chart a click can open is
written out ahead of time as a small JSON file.
"""
import argparse
import json
import shutil
from pathlib import Path

from report import compute, detail, fetch_all

ROOT = Path(__file__).parent
SITE = ROOT / "site"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-fetch", action="store_true", help="build from the cached bars only")
    args = ap.parse_args()

    if not args.no_fetch:
        for failure in fetch_all():
            print("download failed, using cached bars:", failure)
    data = compute()  # raises if there are no bars at all, which leaves the live site untouched

    shutil.rmtree(SITE, ignore_errors=True)
    (SITE / "detail").mkdir(parents=True)
    shutil.copy(ROOT / "dashboard.html", SITE / "index.html")
    (SITE / "state.json").write_text(json.dumps(data))

    scan_start = data["year"]["scan_start"]
    for i, r in enumerate(data["results"]):  # s<i>.json: row i of the scan table
        q = {"ticker": r["ticker"], "bar": r["bar"].rstrip("m"), "strategy": r["strategy"], "params": r["params"]}
        (SITE / "detail" / f"s{i}.json").write_text(json.dumps(detail(q)))
    for i, r in enumerate(data["year"]["rows"]):  # y<i>.json: row i of the one-year table
        q = {"ticker": r["ticker"], "bar": r["src_bar"], "strategy": r["strategy"], "params": r["src_params"], "year": 1}
        (SITE / "detail" / f"y{i}.json").write_text(json.dumps(detail(q, scan_start)))

    size = sum(f.stat().st_size for f in SITE.rglob("*") if f.is_file()) / 1e6
    print(f"Built {SITE} ({len(data['results'])} tests, {len(data['year']['rows'])} one-year rows, {size:.1f} MB)")


if __name__ == "__main__":
    main()
