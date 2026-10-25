"""
Yearly and volatile-period performance columns for the screener output, so
everything about a fund is in one sheet.

  - attach_yearly_stats(): from the yearly returns CSV, how often each fund
    beat / trailed all benchmark indexes (^GSPC, ^DJI, ^IXIC) over the years
    shown in the "Yearly Return (YYYY)" columns, plus percentile buckets.
  - attach_volatile_performance(): for every period in volatile_config.yaml,
    each fund's return from the S&P high to the low ("Volatile Decline: ...")
    and, for bear markets, from the low back to the old high ("Volatile
    Recovery: ..."), plus the same beat/trail and percentile stats.

Volatile-period returns are history and never change, so they are cached in
VOLATILE_RETURNS_CSV; a run only downloads funds (or periods) not yet cached.
Returns are in percent, like Morningstar's Total Return columns.
"""

import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from utils.yf_download import download_prices
from config import (
    BENCHMARK_INDEXES,
    VOLATILE_CONFIG_PATH,
    VOLATILE_DOWNLOAD,
    VOLATILE_RETURNS_CSV,
    YAHOO_RETURNS_DIR,
)

# Shared code in yahoo_returns/ (appended, not prepended, so a same-named
# module there never shadows one in this folder, e.g. database.py).
if YAHOO_RETURNS_DIR not in sys.path:
    sys.path.append(YAHOO_RETURNS_DIR)

from benchmark_stats import add_better_worst_stats, add_percentile_bucket_counts  # noqa: E402
from volatile_periods import load_periods  # noqa: E402

# Shared stat names -> readable column names (prefixed "Yearly " / "Volatile ")
STAT_LABELS: Dict[str, str] = {
    "better": "Beat All Indexes",
    "worst": "Trailed All Indexes",
    "no_null_columns": "Periods With Data",
    "better_%": "Beat %",
    "worst_%": "Trailed %",
    "better_worst_diff": "Beat-Trail Diff",
    "top_10%": "Top 10% Count",
    "top_20%": "Top 20% Count",
    "top_30%": "Top 30% Count",
    "top_40%": "Top 40% Count",
    "top_50%": "Top 50% Count",
    "top_60%": "Top 60% Count",
    "top_70%": "Top 70% Count",
    "top_80%": "Top 80% Count",
    "top_90%": "Top 90% Count",
    "worse_10%": "Bottom 10% Count",
}
PERCENT_STATS = {"better_%", "worst_%", "better_worst_diff"}


def _tickers(df: pd.DataFrame) -> pd.Series:
    return df["Ticker"].astype(str).str.strip().str.upper()


def _benchmark_stats(returns: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """Beat/trail + percentile stats for every non-index row of `returns`
    (tickers x periods, indexes included as rows), with readable names."""
    funds = returns.drop(index=BENCHMARK_INDEXES, errors="ignore")
    stats = add_better_worst_stats(pd.DataFrame(index=funds.index), returns, BENCHMARK_INDEXES)
    stats = add_percentile_bucket_counts(stats, returns, BENCHMARK_INDEXES)
    stats = stats[list(STAT_LABELS)]
    for c in PERCENT_STATS:
        stats[c] = stats[c] * 100.0
    return stats.rename(columns={k: f"{prefix} {v}" for k, v in STAT_LABELS.items()})


COUNT_SUFFIXES = ("Beat All Indexes", "Trailed All Indexes", "Periods With Data", "Count")


def _whole_number_counts(table: pd.DataFrame) -> pd.DataFrame:
    """Show count columns as whole numbers (blank where a fund has no data)."""
    for c in table.columns:
        if str(c).endswith(COUNT_SUFFIXES):
            table[c] = table[c].round().astype("Int64")
    return table


def _insert_after(df: pd.DataFrame, new: pd.DataFrame, after_prefix: str) -> pd.DataFrame:
    """Insert `new` (same index as df) after the last column starting with
    `after_prefix`, or at the end if there is none."""
    out = df.drop(columns=[c for c in new.columns if c in df.columns])
    anchor = [c for c in out.columns if str(c).startswith(after_prefix)]
    at = out.columns.get_loc(anchor[-1]) + 1 if anchor else len(out.columns)
    return pd.concat([out.iloc[:, :at], new, out.iloc[:, at:]], axis=1)


# ---------------------------------------------------------------------------
# Yearly
# ---------------------------------------------------------------------------

def attach_yearly_stats(df: pd.DataFrame, csv_path: str, n_years: int) -> pd.DataFrame:
    """Add "Yearly ..." beat/trail and percentile columns over the last
    `n_years` complete years, placed after the Yearly Return columns."""
    if not os.path.exists(csv_path):
        print(f"  Warning: yearly returns file not found ({csv_path}) -- skipping yearly stats.")
        return df

    yearly = pd.read_csv(csv_path, index_col=0)
    yearly.index = yearly.index.astype(str).str.strip().str.upper()
    yearly = yearly[~yearly.index.duplicated(keep="last")]
    year_cols = sorted((c for c in yearly.columns if str(c).isdigit()), key=int)[-n_years:]

    keys = _tickers(df)
    universe = list(dict.fromkeys(list(keys) + BENCHMARK_INDEXES))
    returns = yearly.reindex(universe)[year_cols]

    stats = _whole_number_counts(_benchmark_stats(returns, "Yearly").reindex(keys))
    stats.index = df.index
    print(f"  Yearly stats over {year_cols[0]}-{year_cols[-1]} added "
          f"({int(stats['Yearly Periods With Data'].gt(0).sum())}/{len(df)} funds with data).")
    return _insert_after(df, stats, "Yearly Return (")


# ---------------------------------------------------------------------------
# Volatile periods
# ---------------------------------------------------------------------------

# Cache columns include the dates, so editing a period's start/end/recovery
# in volatile_config.yaml gives a new key and the returns are recomputed
# (a key based on `id` alone would keep serving the old dates' returns).
def _decline_col(p: Dict[str, Any]) -> str:
    return f"{p['id']} decline {p['start']}..{p['end']}"


def _recovery_col(p: Dict[str, Any]) -> str:
    return f"{p['id']} recovery {p['end']}..{p['recovery']}"


def _download_closes(tickers: List[str], start: str, end: str) -> Tuple[pd.DataFrame, List[str]]:
    """Dividend/split-adjusted daily closes (tickers as columns), in batches.

    Uses auto_adjust=True and the "Close" column: yfinance adds an
    "Adj Close" column only for tickers that FAILED, so reading it would drop
    every good ticker in a batch that contains a delisted one.

    Also returns the tickers that failed to download (network / rate
    limit, after retries), so they are retried next run instead of cached
    as "no data".
    """
    batch_size = VOLATILE_DOWNLOAD["batch_size"]
    batches = [tickers[i:i + batch_size] for i in range(0, len(tickers), batch_size)]
    frames, failed = [], []
    for n, batch in enumerate(batches, 1):
        print(f"    Volatile periods: downloading batch {n}/{len(batches)} ({len(batch)} tickers)...")
        close, batch_failed = download_prices(
            batch, "Close", retries=VOLATILE_DOWNLOAD["max_retries"],
            start=start, end=end, auto_adjust=True,
        )
        if not close.empty:
            frames.append(close)
        failed.extend(batch_failed)
        if n < len(batches):
            time.sleep(VOLATILE_DOWNLOAD["rest_delay_seconds"] + random.uniform(0, VOLATILE_DOWNLOAD["jitter_seconds"]))
    if not frames:
        return pd.DataFrame(), failed
    closes = pd.concat(frames, axis=1)
    closes.index = pd.to_datetime(closes.index).normalize()
    return closes.sort_index(), failed


def _period_return(prices: pd.Series, start: str, end: str) -> float:
    """First close on/after start -> last close on/before end; NaN if the
    fund has fewer than two closes in that window (e.g. not launched yet)."""
    window = prices.loc[pd.Timestamp(start):pd.Timestamp(end)]
    if len(window) < 2:
        return float("nan")
    return float(window.iloc[-1] / window.iloc[0] - 1)


def _update_volatile_cache(tickers: List[str], periods: List[Dict[str, Any]], cache_path: str) -> pd.DataFrame:
    """Load the cache and compute any missing (ticker, period) cells."""
    cols = [_decline_col(p) for p in periods] + [_recovery_col(p) for p in periods if p.get("recovery")]
    cache = pd.read_csv(cache_path, index_col=0) if os.path.exists(cache_path) else pd.DataFrame()
    cache.index = cache.index.astype(str)

    new_cols = [c for c in cols if c not in cache.columns]
    to_fetch = [t for t in tickers if t not in cache.index]
    if new_cols:
        # new period or changed dates: recompute it for every cached ticker
        print(f"  Volatile periods: {len(new_cols)} new or changed period column(s), recomputing for all tickers.")
        to_fetch = list(dict.fromkeys(list(cache.index) + list(tickers)))

    if not to_fetch:
        return cache.reindex(columns=cols)

    start = str(min(p["start"] for p in periods))
    last = max(pd.Timestamp(p.get("recovery") or p["end"]) for p in periods)
    end = (last + pd.Timedelta(days=1)).strftime("%Y-%m-%d")  # yfinance `end` is exclusive
    print(f"  Volatile periods: computing returns for {len(to_fetch)} ticker(s) ({start} -> {last.date()})...")
    closes, failed = _download_closes(to_fetch, start, end)
    if failed:
        print(f"  Volatile periods: {len(failed)} ticker(s) not downloaded; they will be retried next run.")

    rows = {}
    for t in [t for t in to_fetch if t not in failed]:
        prices = closes[t].dropna() if t in closes.columns else pd.Series(dtype="float64")
        row = {_decline_col(p): _period_return(prices, p["start"], p["end"]) for p in periods}
        row.update({_recovery_col(p): _period_return(prices, p["end"], p["recovery"]) for p in periods if p.get("recovery")})
        rows[t] = row
    fresh = pd.DataFrame.from_dict(rows, orient="index", columns=cols)

    cache = pd.concat([cache.drop(index=[t for t in fresh.index if t in cache.index]), fresh])
    cache = cache.reindex(columns=cols)
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    cache.sort_index().to_csv(cache_path)
    print(f"  Volatile periods cache updated: {cache_path}")
    return cache


def attach_volatile_performance(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Add "Volatile Decline/Recovery: <period>" return columns (percent) and
    "Volatile ..." beat/trail + percentile stats (based on the declines),
    placed after the Yearly columns."""
    periods = load_periods(Path(VOLATILE_CONFIG_PATH))
    if not periods:
        print(f"  Warning: no periods in {VOLATILE_CONFIG_PATH} -- skipping volatile performance.")
        return df, {}
    periods = sorted(periods, key=lambda p: str(p["start"]))

    keys = _tickers(df)
    universe = list(dict.fromkeys(list(keys) + BENCHMARK_INDEXES))
    cache = _update_volatile_cache(universe, periods, VOLATILE_RETURNS_CSV)
    returns = cache.reindex(universe)

    decline = returns[[_decline_col(p) for p in periods]]
    stats = _benchmark_stats(decline, "Volatile")

    out_cols = {}
    for p in periods:
        out_cols[f"Volatile Decline: {p['name']}"] = returns[_decline_col(p)] * 100.0
        if p.get("recovery"):
            out_cols[f"Volatile Recovery: {p['name']}"] = returns[_recovery_col(p)] * 100.0
    table = _whole_number_counts(pd.DataFrame(out_cols).join(stats).reindex(keys))
    table.index = df.index

    with_data = int(stats["Volatile Periods With Data"].reindex(keys).gt(0).sum())
    print(f"  Volatile performance for {len(periods)} periods added ({with_data}/{len(df)} funds with data).")
    report = {"periods": len(periods), "funds_with_data": with_data, "funds_total": len(df)}
    anchor = "Yearly " if any(str(c).startswith("Yearly ") for c in df.columns) else "Total Return ("
    return _insert_after(df, table, anchor), report


# ---------------------------------------------------------------------------
# Benchmark rows for the report
# ---------------------------------------------------------------------------

BENCHMARK_NAMES: Dict[str, str] = {
    "^GSPC": "Benchmark: S&P 500",
    "^DJI": "Benchmark: Dow Jones Industrial Average",
    "^IXIC": "Benchmark: NASDAQ Composite",
}


def append_benchmark_rows(df: pd.DataFrame, yearly_csv: str) -> pd.DataFrame:
    """Return df with one row per benchmark index (^GSPC, ^DJI, ^IXIC) at the
    bottom, so the funds can be compared against them in the report.

    Only the "Yearly Return (YYYY)" and "Volatile Decline/Recovery: ..."
    columns are filled (from the same caches as the funds); every other
    column -- Morningstar data, scores, ranks, flags, stats -- stays blank,
    so the rows are never scored, ranked, selected or alerted on.
    """
    rows = pd.DataFrame({"Ticker": BENCHMARK_INDEXES}, index=range(len(BENCHMARK_INDEXES)))
    if "Name" in df.columns:
        rows["Name"] = [BENCHMARK_NAMES.get(t, f"Benchmark: {t}") for t in BENCHMARK_INDEXES]

    # Yearly returns
    year_cols = {c: c[len("Yearly Return ("):-1] for c in df.columns if str(c).startswith("Yearly Return (")}
    if year_cols and os.path.exists(yearly_csv):
        yearly = pd.read_csv(yearly_csv, index_col=0).reindex(BENCHMARK_INDEXES)
        for col, year in year_cols.items():
            if year in yearly.columns:
                rows[col] = yearly[year].to_numpy() * 100.0

    # Volatile-period returns (same cache keys as the funds)
    if os.path.exists(VOLATILE_RETURNS_CSV):
        cache = pd.read_csv(VOLATILE_RETURNS_CSV, index_col=0).reindex(BENCHMARK_INDEXES)
        for p in load_periods(Path(VOLATILE_CONFIG_PATH)):
            pairs = [(f"Volatile Decline: {p['name']}", _decline_col(p))]
            if p.get("recovery"):
                pairs.append((f"Volatile Recovery: {p['name']}", _recovery_col(p)))
            for out_col, key in pairs:
                if out_col in df.columns and key in cache.columns:
                    rows[out_col] = cache[key].to_numpy() * 100.0

    return pd.concat([df, rows.reindex(columns=df.columns)], ignore_index=True)
