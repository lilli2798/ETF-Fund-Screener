"""
Batch-pull Yahoo Finance sector/sub-industry data for large ETF ticker
lists, in chunks of 200 (configurable), to support the sector-
dispersion analysis described in docs/column_glossary.md (Section 9 /
the dispersion-triggered pull rule).

For each ticker, this script pulls (via yfinance's FundsData scraper):
  - sector_weightings   -- the same coarse 11-GICS-sector breakdown
                           Morningstar already gives us (kept for
                           completeness / cross-checking).
  - top_holdings        -- individual stock symbols + weights held by
                           the ETF (usually top ~10-25 names,
                           depending on what Yahoo exposes).

Then, for every UNIQUE underlying stock symbol found across all
top_holdings (deduplicated -- many ETFs share mega-cap names), it
looks up that stock's `industry` field (finer-grained than `sector`,
e.g. "Software - Infrastructure" vs "Semiconductors") via yf.Tickers
batch info calls.

Output: a single CSV with one row per (ETF ticker, holding symbol,
holding weight, holding industry), plus a second summary CSV with one
row per ETF showing an industry-concentration (Herfindahl-style)
score, so you can see which funds actually need the sub-industry
split before spending more effort on it.

Usage:
    python3 utils/fetch_yahoo_sector_data.py ticker_list.txt \\
        --output-dir output --chunk-size 200

Resuming an interrupted run:
    python3 utils/fetch_yahoo_sector_data.py ticker_list.txt \\
        --output-dir output --resume

Where ticker_list.txt has one ticker per line (blank lines and lines
starting with # are ignored). No hard limit on ticker-list size --
runtime and rate-limit risk scale with the number of UNIQUE underlying
holding symbols (step 3 below), not just the ETF count, since popular
mega-caps get deduplicated but a very large or diverse ETF list can
still produce thousands of unique symbols to look up.

NOTES / LIMITATIONS:
  - Yahoo does not officially support bulk pulls at this volume; this
    script chunks requests, adds a delay between chunks, and retries
    failed tickers/chunks with exponential backoff to reduce (but not
    eliminate) the chance of rate-limiting. If you see repeated
    failures, slow down further (increase --sleep-between-chunks) or
    reduce --chunk-size.
  - Every chunk's results are appended to the output CSVs immediately
    (checkpointing), not just written once at the end. If the script
    is interrupted or rate-limited partway through a long run, nothing
    already fetched is lost, and re-running with --resume will skip
    tickers/symbols already present in the existing output files.
  - top_holdings weights often only cover a fraction of AUM (typically
    top 10-25 names), so the Herfindahl score here is an APPROXIMATION
    bounded by data coverage, not a true full-portfolio calculation.
    The output includes a `Coverage_Pct` column so you can see exactly
    how much of each fund's weight the calculation is based on.
"""

import argparse
import os
import time
from typing import Dict, List, Optional, Set

import pandas as pd
import yfinance as yf

DEFAULT_CHUNK_SIZE = 200
DEFAULT_SLEEP_BETWEEN_CHUNKS = 2.0  # seconds -- polite pacing to avoid throttling
DEFAULT_SLEEP_BETWEEN_TICKERS = 0.0  # seconds -- extra per-ticker delay if needed
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF_BASE = 2.0  # seconds -- doubles each retry (2s, 4s, 8s, ...)

HOLDINGS_DETAIL_FILENAME = "yahoo_holdings_detail.csv"
SECTOR_WEIGHTINGS_FILENAME = "yahoo_sector_weightings.csv"
CONCENTRATION_FILENAME = "yahoo_industry_concentration.csv"
FAILED_TICKERS_FILENAME = "yahoo_fetch_failed_tickers.txt"


def load_ticker_list(list_file_path: str) -> List[str]:
    with open(list_file_path, "r") as f:
        lines = [line.strip() for line in f.readlines()]
    return [line for line in lines if line and not line.startswith("#")]


def chunk_list(items: List[str], chunk_size: int) -> List[List[str]]:
    return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]


def retry_with_backoff(fn, max_retries: int, backoff_base: float, label: str):
    """
    Call fn() with no args, retrying on exception up to max_retries
    times with exponential backoff (backoff_base, backoff_base*2,
    backoff_base*4, ...). Raises the last exception if all retries
    are exhausted.
    """
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                wait = backoff_base * (2 ** (attempt - 1))
                print(f"  [retry {attempt}/{max_retries}] {label} failed ({exc}); waiting {wait:.1f}s...")
                time.sleep(wait)
    raise last_exc


def load_already_fetched_tickers(output_dir: str) -> Set[str]:
    """For --resume: read existing holdings-detail CSV to find tickers already done."""
    path = os.path.join(output_dir, HOLDINGS_DETAIL_FILENAME)
    if not os.path.exists(path):
        return set()
    try:
        df = pd.read_csv(path, usecols=["ETF_Ticker"])
        return set(df["ETF_Ticker"].astype(str).unique().tolist())
    except Exception:
        return set()


def append_df_to_csv(df: pd.DataFrame, path: str) -> None:
    """Append df to path, writing header only if the file doesn't exist yet."""
    if df.empty:
        return
    file_exists = os.path.exists(path)
    df.to_csv(path, mode="a", index=False, header=not file_exists)


def fetch_fund_data_for_ticker(ticker: str, max_retries: int, backoff_base: float) -> Optional[Dict]:
    """
    Fetch sector_weightings and top_holdings for a single ETF ticker,
    retrying transient failures with exponential backoff. Returns None
    (and prints a warning) if the ticker has no fund data (e.g. it's
    not actually an ETF/fund) or if all retries are exhausted.
    """
    def _do_fetch():
        t = yf.Ticker(ticker)
        fd = t.funds_data
        if fd is None:
            return None
        sector_weightings = fd.sector_weightings or {}
        top_holdings_df = fd.top_holdings
        if top_holdings_df is None or top_holdings_df.empty:
            top_holdings_df = pd.DataFrame()
        return {
            "ticker": ticker,
            "sector_weightings": sector_weightings,
            "top_holdings": top_holdings_df,
        }

    try:
        result = retry_with_backoff(_do_fetch, max_retries, backoff_base, label=f"fetch({ticker})")
    except Exception as exc:
        print(f"  [error] {ticker}: giving up after {max_retries} attempts ({exc}).")
        return None

    if result is None:
        print(f"  [warn] {ticker}: no funds_data available (not a fund, or unlisted).")
    elif result["top_holdings"].empty:
        print(f"  [warn] {ticker}: no top_holdings data.")
    return result


def fetch_fund_data_for_chunk(
    tickers: List[str],
    sleep_between_tickers: float,
    max_retries: int,
    backoff_base: float,
) -> List[Dict]:
    results = []
    for ticker in tickers:
        data = fetch_fund_data_for_ticker(ticker, max_retries, backoff_base)
        if data is not None:
            results.append(data)
        if sleep_between_tickers > 0:
            time.sleep(sleep_between_tickers)
    return results


def fetch_industry_lookup_for_chunk(
    symbols: List[str],
    max_retries: int,
    backoff_base: float,
) -> Dict[str, Dict[str, str]]:
    def _do_lookup():
        tickers_obj = yf.Tickers(" ".join(symbols))
        chunk_lookup = {}
        for symbol in symbols:
            info = tickers_obj.tickers[symbol].info
            chunk_lookup[symbol] = {
                "sector": info.get("sector", ""),
                "industry": info.get("industry", ""),
            }
        return chunk_lookup

    try:
        return retry_with_backoff(_do_lookup, max_retries, backoff_base, label=f"industry_lookup({len(symbols)} symbols)")
    except Exception as exc:
        print(f"  [error] industry lookup failed for this chunk after {max_retries} attempts ({exc}); "
              f"marking all {len(symbols)} symbols as unknown.")
        return {s: {"sector": "", "industry": ""} for s in symbols}


def build_holdings_detail_df(fund_results: List[Dict], industry_lookup: Dict[str, Dict[str, str]]) -> pd.DataFrame:
    rows = []
    for fund in fund_results:
        ticker = fund["ticker"]
        th = fund["top_holdings"]
        if th is None or th.empty:
            continue
        weight_col = next((c for c in th.columns if "percent" in c.lower() or "weight" in c.lower()), th.columns[0])
        for symbol, row in th.iterrows():
            info = industry_lookup.get(str(symbol), {"sector": "", "industry": ""})
            rows.append({
                "ETF_Ticker": ticker,
                "Holding_Symbol": symbol,
                "Holding_Weight": row.get(weight_col),
                "Holding_Sector": info["sector"],
                "Holding_Industry": info["industry"],
            })
    return pd.DataFrame(rows)


def build_sector_weightings_df(fund_results: List[Dict]) -> pd.DataFrame:
    rows = []
    for fund in fund_results:
        row = {"ETF_Ticker": fund["ticker"]}
        row.update(fund["sector_weightings"])
        rows.append(row)
    return pd.DataFrame(rows)


def compute_industry_concentration(holdings_detail_df: pd.DataFrame) -> pd.DataFrame:
    """
    Per ETF: Herfindahl-style concentration score on Holding_Industry
    (sum of squared industry weight shares, among covered holdings
    only), plus Coverage_Pct = how much of the fund's weight the
    top_holdings data actually represents (bounded approximation --
    see module docstring). Computed once at the end over the FULL
    accumulated holdings-detail data (not per-chunk), since a fund's
    holdings could theoretically span... in practice always one chunk,
    but this keeps the calculation correct regardless.
    """
    if holdings_detail_df.empty:
        return pd.DataFrame(columns=[
            "ETF_Ticker", "Coverage_Pct", "Num_Distinct_Industries",
            "Top_Industry", "Top_Industry_Share_Of_Covered",
            "Industry_Herfindahl_Score",
        ])

    rows = []
    for ticker, group in holdings_detail_df.groupby("ETF_Ticker"):
        total_weight = group["Holding_Weight"].sum()
        if total_weight is None or total_weight == 0:
            rows.append({
                "ETF_Ticker": ticker, "Coverage_Pct": 0.0,
                "Num_Distinct_Industries": 0, "Top_Industry": None,
                "Top_Industry_Share_Of_Covered": None,
                "Industry_Herfindahl_Score": None,
            })
            continue

        industry_weights = group.groupby("Holding_Industry")["Holding_Weight"].sum()
        industry_shares = industry_weights / total_weight
        herfindahl = (industry_shares ** 2).sum()
        top_industry = industry_shares.idxmax()
        top_share = industry_shares.max()

        rows.append({
            "ETF_Ticker": ticker,
            "Coverage_Pct": total_weight,
            "Num_Distinct_Industries": industry_weights.shape[0],
            "Top_Industry": top_industry,
            "Top_Industry_Share_Of_Covered": top_share,
            "Industry_Herfindahl_Score": herfindahl,
        })
    return pd.DataFrame(rows).sort_values("Industry_Herfindahl_Score", ascending=True)


def main():
    parser = argparse.ArgumentParser(
        description="Batch-pull Yahoo Finance sector/top-holdings data for a large ETF ticker list, with checkpointing."
    )
    parser.add_argument("ticker_list", help="Path to a text file with one ETF ticker per line.")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
                         help="Number of tickers/symbols to fetch per batch (default 200).")
    parser.add_argument("--sleep-between-chunks", type=float, default=DEFAULT_SLEEP_BETWEEN_CHUNKS,
                         help="Seconds to pause between chunks (default 2.0).")
    parser.add_argument("--sleep-between-tickers", type=float, default=DEFAULT_SLEEP_BETWEEN_TICKERS,
                         help="Seconds to pause between individual ticker calls within a chunk (default 0.0).")
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES,
                         help="Max retry attempts per ticker/chunk on failure (default 3).")
    parser.add_argument("--retry-backoff-base", type=float, default=DEFAULT_RETRY_BACKOFF_BASE,
                         help="Base seconds for exponential backoff between retries (default 2.0).")
    parser.add_argument("--resume", action="store_true",
                         help="Skip tickers already present in the existing holdings-detail CSV in --output-dir.")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    holdings_path = os.path.join(args.output_dir, HOLDINGS_DETAIL_FILENAME)
    sector_path = os.path.join(args.output_dir, SECTOR_WEIGHTINGS_FILENAME)
    concentration_path = os.path.join(args.output_dir, CONCENTRATION_FILENAME)
    failed_path = os.path.join(args.output_dir, FAILED_TICKERS_FILENAME)

    tickers = load_ticker_list(args.ticker_list)
    print(f"Loaded {len(tickers)} tickers from {args.ticker_list}.")

    if args.resume:
        already_done = load_already_fetched_tickers(args.output_dir)
        if already_done:
            before = len(tickers)
            tickers = [t for t in tickers if t not in already_done]
            print(f"--resume: skipping {before - len(tickers)} tickers already present in {holdings_path}.")

    if not tickers:
        print("Nothing left to fetch. Exiting.")
        return

    chunks = chunk_list(tickers, args.chunk_size)
    failed_tickers: List[str] = []
    all_fund_results_for_symbol_collection: List[Dict] = []

    print(f"\n=== Step 1+2: Fetching fund-level data and checkpointing per chunk ({len(chunks)} chunks) ===")
    for i, chunk in enumerate(chunks, start=1):
        print(f"Fetching chunk {i}/{len(chunks)} ({len(chunk)} tickers)...")
        chunk_results = fetch_fund_data_for_chunk(
            chunk, args.sleep_between_tickers, args.max_retries, args.retry_backoff_base
        )
        fetched_tickers_in_chunk = {r["ticker"] for r in chunk_results}
        failed_tickers.extend([t for t in chunk if t not in fetched_tickers_in_chunk])

        # Checkpoint sector weightings immediately (top_holdings is checkpointed
        # after industry lookup below, since it needs the industry join first).
        sector_df_chunk = build_sector_weightings_df(chunk_results)
        append_df_to_csv(sector_df_chunk, sector_path)

        all_fund_results_for_symbol_collection.extend(chunk_results)

        if i < len(chunks) and args.sleep_between_chunks > 0:
            print(f"  Sleeping {args.sleep_between_chunks}s before next chunk...")
            time.sleep(args.sleep_between_chunks)

    print(f"\nFetched fund data for {len(all_fund_results_for_symbol_collection)}/{len(tickers)} tickers this run.")

    unique_symbols = sorted({
        str(sym)
        for fund in all_fund_results_for_symbol_collection
        for sym in (fund["top_holdings"].index.tolist() if not fund["top_holdings"].empty else [])
    })
    print(f"\n=== Step 3: Looking up industry for {len(unique_symbols)} unique underlying holding symbols ===")
    symbol_chunks = chunk_list(unique_symbols, args.chunk_size)
    industry_lookup: Dict[str, Dict[str, str]] = {}
    for i, symbol_chunk in enumerate(symbol_chunks, start=1):
        print(f"Looking up industry chunk {i}/{len(symbol_chunks)} ({len(symbol_chunk)} symbols)...")
        industry_lookup.update(
            fetch_industry_lookup_for_chunk(symbol_chunk, args.max_retries, args.retry_backoff_base)
        )
        if i < len(symbol_chunks) and args.sleep_between_chunks > 0:
            time.sleep(args.sleep_between_chunks)

    print("\n=== Step 4: Building and checkpointing holdings-detail rows ===")
    holdings_detail_df_this_run = build_holdings_detail_df(all_fund_results_for_symbol_collection, industry_lookup)
    append_df_to_csv(holdings_detail_df_this_run, holdings_path)

    if failed_tickers:
        with open(failed_path, "a") as f:
            for t in failed_tickers:
                f.write(t + "\n")
        print(f"\n{len(failed_tickers)} tickers failed this run -- logged to {failed_path}. "
              f"Re-run with --resume (after fixing the list) to retry only what's missing.")

    print("\n=== Step 5: Recomputing industry concentration over ALL accumulated data ===")
    full_holdings_detail_df = pd.read_csv(holdings_path) if os.path.exists(holdings_path) else holdings_detail_df_this_run
    concentration_df = compute_industry_concentration(full_holdings_detail_df)
    concentration_df.to_csv(concentration_path, index=False)  # full overwrite -- this one is cheap to recompute wholesale

    print(f"\nHoldings detail (cumulative) -> {holdings_path}")
    print(f"Sector weightings (cumulative) -> {sector_path}")
    print(f"Industry concentration (recomputed from all data) -> {concentration_path}")
    print("\nTip: sort yahoo_industry_concentration.csv by Industry_Herfindahl_Score ascending")
    print("     to find the funds with the MOST industry mix (i.e. the ones where Morningstar")
    print("     Category-relative normalization is most likely hiding sub-sector differences).")


if __name__ == "__main__":
    main()
