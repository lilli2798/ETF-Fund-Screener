"""
Yearly History Cache Manager

This module manages the yearly returns cache for ETF tickers.
It provides functions to build, update, and load the cache from a CSV file.

The cache stores yearly returns for each ticker from 2006-01-01 to the previous year.
This is separate from the interactive analysis which may only need short-term returns.

New funds are added automatically: every screener run passes its tickers
to build_yearly_history_cache(), which downloads only the ones not in the
file yet (performance.update_yearly_cache). Funds with no complete year yet
are saved as an empty row so they aren't downloaded every night.

Usage (once a year, after the year ends -- the January GitHub job):
    python yearly_cache_manager.py
    # adds the finished year for every fund in the file and refills empty rows
"""

import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from yahoo_config import DEFAULT_CONFIG

# utils/yf_download.py (in etf_screener/) tells Yahoo's "rate limited" answers
# apart from funds that really have no data.
sys.path.append(str(Path(__file__).resolve().parent.parent))
from utils.yf_download import download_prices  # noqa: E402


# =========================================================================
# UTILITY FUNCTIONS
# =========================================================================

def to_date(x):
    """Convert input to pandas datetime and normalize to midnight.
    
    Args:
        x: Date string, datetime object, or pandas-compatible date
    
    Returns:
        pandas Timestamp normalized to midnight
    """
    return pd.to_datetime(x).normalize()


def make_return_series(adj_df, start_dt, end_dt):
    """Calculate return for a single ticker over a specific date range.
    
    Args:
        adj_df: DataFrame with adjusted close prices (single column)
        start_dt: Start date for return calculation
        end_dt: End date for return calculation
    
    Returns:
        Series with ticker as index and return value.
        Return = (end_price / start_price) - 1
        Returns empty Series if insufficient data.
    """
    if adj_df.empty:
        return pd.Series(dtype="float64")

    s = adj_df.loc[(adj_df.index >= start_dt) & (adj_df.index <= end_dt)]
    if len(s) < 2:
        return pd.Series(dtype="float64")

    return (s.iloc[-1] / s.iloc[0]) - 1


# =========================================================================
# DATA DOWNLOAD
# =========================================================================

def _get_rate_limit_config(config: Dict = None) -> Dict:
    """Extract rate limiting configuration with defaults."""
    if config is None:
        config = DEFAULT_CONFIG
    rate_config = config.get("rate_limiting", {})
    return {
        "batch_size": rate_config.get("batch_size", 50),
        "rest_delay": rate_config.get("rest_delay_seconds", 10.0),
        "jitter": rate_config.get("rest_delay_jitter_seconds", 10.0),
        "max_retries": rate_config.get("max_download_retries", 3)
    }


def _batch_generator(all_symbols: List[str], batch_size: int):
    """Generate batches with progress information.
    
    Args:
        all_symbols: List of symbols to process
        batch_size: Number of symbols per batch
    
    Yields:
        Tuple of (batch_list, batch_number, total_batches)
    """
    total_batches = (len(all_symbols) + batch_size - 1) // batch_size
    for i in range(0, len(all_symbols), batch_size):
        batch = all_symbols[i:i + batch_size]
        batch_num = i // batch_size + 1
        print(f"  Batch {batch_num}/{total_batches}: {len(batch)} symbols")
        yield batch, batch_num, total_batches

def download_adj_close(tickers, start, end, config: Dict = None):
    """Download adjusted close prices with rate limiting and error handling.
    
    Args:
        tickers: List of ticker symbols to download
        start: Start date (string or datetime)
        end: End date (string or datetime)
        config: Configuration dictionary with rate limiting settings
    
    Returns:
        DataFrame with adjusted close prices (tickers as columns, dates as index).
        Returns empty DataFrame if download fails completely.
    
    Features:
        - Batch processing with configurable batch size
        - Rate limiting with delays and random jitter
        - Retry logic for failed batches
        - Includes benchmark indexes from config
    """
    rate_config = _get_rate_limit_config(config)
    batch_size = rate_config["batch_size"]
    rest_delay = rate_config["rest_delay"]
    jitter = rate_config["jitter"]
    max_retries = rate_config["max_retries"]
    
    # For cache manager, don't automatically add indexes
    # Only download the requested tickers
    all_symbols = tickers
    
    print(f"Downloading data for {len(all_symbols)} symbols...")
    
    # Process in batches
    adj = pd.DataFrame()
    failed_symbols = []
    
    for batch, batch_num, total_batches in _batch_generator(all_symbols, batch_size):
        
        retry_count = 0
        while retry_count < max_retries:
            try:
                # retries Yahoo rate limits; still-failing tickers are reported below
                batch_adj, batch_failed = download_prices(batch, "Close", start=start, end=end, auto_adjust=True)
                failed_symbols.extend(batch_failed)
                if batch_adj.empty:
                    print(f"    No data returned for batch {batch_num}")
                    break
                
                adj = pd.concat([adj, batch_adj], axis=1)
                break
                
            except Exception as e:
                retry_count += 1
                if retry_count < max_retries:
                    wait_time = rest_delay + random.uniform(0, jitter)
                    print(f"    Retry {retry_count}/{max_retries} after {wait_time:.1f}s: {e}")
                    time.sleep(wait_time)
                else:
                    print(f"    Failed after {max_retries} retries: {e}")
                    failed_symbols.extend(batch)
        
        # Rate limiting between batches
        if batch_num < total_batches:
            wait_time = rest_delay + random.uniform(0, jitter)
            print(f"  Waiting {wait_time:.1f}s before next batch...")
            time.sleep(wait_time)
    
    if failed_symbols:
        print(f"  Failed to download {len(failed_symbols)} symbols: {failed_symbols[:10]}...")
    
    if isinstance(adj, pd.Series):
        adj = adj.to_frame()
    
    adj.index = pd.to_datetime(adj.index).normalize()
    return adj.sort_index()


# =========================================================================
# CSV CACHE FUNCTIONS
# =========================================================================

def load_yearly_history_csv(cache_path: str) -> pd.DataFrame:
    """Load yearly returns cache from CSV file.
    
    Args:
        cache_path: Path to the CSV cache file (e.g., 'sources/etf_yearly_history.csv')
    
    Returns:
        DataFrame with tickers as index and years as columns containing yearly returns.
        Returns empty DataFrame if file doesn't exist or fails to load.
    """
    if not Path(cache_path).exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(cache_path, index_col=0)
        return df
    except Exception:
        return pd.DataFrame()


def save_yearly_history_csv(cache_path: str, df: pd.DataFrame) -> None:
    """Save yearly returns cache to CSV file.
    
    Args:
        cache_path: Path to save the CSV cache file
        df: DataFrame with tickers as index and years as columns
    
    Returns:
        None
    """
    cache_dir = Path(cache_path).parent
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Sort columns in ascending order (chronological)
    df_sorted = df[sorted(df.columns)]
    df_sorted.to_csv(cache_path)


# =========================================================================
# YEARLY UPDATE FUNCTION
# =========================================================================

def add_missing_years(config: Dict = None) -> List[int]:
    """Add any completed year(s) missing from the cache for tickers already in it.

    Meant to run once a year (early January): finds year columns between
    history_start_date and the previous calendar year that the cache does
    not have yet, downloads only that date range for every cached ticker
    (including the benchmark indexes), and appends the new year column(s).
    Existing values are never changed.
    """
    if config is None:
        config = DEFAULT_CONFIG

    cache_config = config.get("caching", {})
    cache_path = cache_config.get("yearly_returns_cache_path", "sources/etf_yearly_history.csv")
    history_start_year = to_date(cache_config.get("history_start_date", "2006-01-01")).year

    cached_df = load_yearly_history_csv(cache_path)
    if cached_df.empty:
        print("No existing cache found -- nothing to extend (new tickers are handled by build_yearly_history_cache).")
        return []

    previous_year = datetime.now().year - 1
    missing_years = [
        y for y in range(history_start_year, previous_year + 1)
        if str(y) not in cached_df.columns
    ]
    if not missing_years:
        print(f"Cache already has every year through {previous_year}. No yearly update needed.")
        return []

    tickers = cached_df.index.tolist()
    print(f"Adding year(s) {missing_years} for {len(tickers)} cached tickers...")

    # yfinance's `end` is exclusive, so end on Jan 1 to include Dec 31.
    adj = download_adj_close(
        tickers,
        start=f"{missing_years[0]}-01-01",
        end=f"{missing_years[-1] + 1}-01-01",
        config=config,
    )
    if adj.empty:
        print("No data downloaded. Cache left unchanged.")
        return []

    for year in missing_years:
        year_start = pd.Timestamp(f"{year}-01-01")
        year_end = pd.Timestamp(f"{year}-12-31")
        year_returns = {}
        for ticker in tickers:
            if ticker not in adj.columns:
                continue
            r = make_return_series(adj[[ticker]].dropna(), year_start, year_end)
            if ticker in r.index:
                year_returns[ticker] = r[ticker]
        cached_df[str(year)] = pd.Series(year_returns)
        print(f"  {year}: returns for {len(year_returns)}/{len(tickers)} tickers")

    save_yearly_history_csv(cache_path, cached_df)
    print(f"Cache updated: {cache_path}")
    return missing_years


# =========================================================================
# MAIN CACHE BUILD FUNCTION
# =========================================================================

def build_yearly_history_cache(config: Dict = None, tickers=(), retry_empty: bool = True) -> List[str]:
    """Add funds to the yearly history cache (or build it from scratch).
    
    Args:
        config: Configuration dictionary containing paths and caching settings
        tickers: funds to have in the cache; only the ones not in it yet are downloaded
        retry_empty: also re-download cached funds whose row is empty (the
            January job does; the nightly screener doesn't, to stay fast)
    
    Returns:
        Tickers whose rows were added or refilled (have data now).
    
    Workflow:
        1. Take the tickers passed in
        2. Load existing cache if it exists
        3. Identify tickers to download: not in the cache, or (retry_empty) cached with no data
        4. Download data from 2006-01-01 to previous year 12-31 for new tickers
        5. Calculate yearly returns for each complete year
        6. Merge with existing cache and save to sources/etf_yearly_history.csv
        7. Save funds Yahoo had no complete year for as empty rows
    
    Note: This function preserves existing cache data. A batch that fails to
    download is not saved, so its funds are tried again on the next run.
    """
    if config is None:
        config = DEFAULT_CONFIG
    
    cache_config = config.get("caching", {})
    history_start_date = cache_config.get("history_start_date", "2006-01-01")
    cache_path = cache_config.get("yearly_returns_cache_path", "sources/etf_yearly_history.csv")
    
    # Step 1: tickers already in the cache are skipped; cached tickers not
    # passed in are kept.
    tickers = sorted({str(t).strip().upper() for t in tickers if str(t).strip() and str(t).strip().upper() != "NAN"})
    
    # Step 3: Load existing cache to preserve existing data
    cached_df = load_yearly_history_csv(cache_path)
    
    if not cached_df.empty:
        print(f"Existing cache has {len(cached_df)} tickers")
        # Get tickers from cache and remove duplicates from input
        cached_tickers = set(cached_df.index.tolist())
        input_tickers = set(tickers)
        new_tickers = input_tickers - cached_tickers
        # Tickers whose cached row is completely empty (e.g. added before
        # they had a full trading history, or a failed download) are retried
        # too -- otherwise they would stay empty forever.
        empty_tickers = set(cached_df.index[cached_df.isna().all(axis=1)]) if retry_empty else set()
        tickers_to_add = sorted(new_tickers | empty_tickers)
        print(f"Found {len(new_tickers)} new tickers (not in cache) and "
              f"{len(empty_tickers)} cached tickers with no data to retry")
    else:
        print("No existing cache found, building from scratch...")
        tickers_to_add = tickers
    
    if not tickers_to_add:
        print("All tickers already in cache. No update needed.")
        return []
    
    # Step 4: Download data from 2006-01-01 to previous year 12-31
    current_year = datetime.now().year
    previous_year = current_year - 1
    beginning_date = history_start_date
    ending_date = f"{previous_year}-12-31"
    
    print(f"Downloading data from {beginning_date} to {ending_date} for {len(tickers_to_add)} new tickers...")
    
    # Step 5: Download and calculate incrementally for better performance
    print("Downloading and calculating yearly returns incrementally...")
    beginning_date_dt = to_date(beginning_date)
    ending_date_dt = to_date(ending_date)
    
    yearly_data = {}
    failed_tickers = []   # download failed: not saved, tried again next run
    no_data_tickers = []  # Yahoo has no complete year: saved as an empty row
    
    # Process in batches to overlap download and calculation
    rate_config = _get_rate_limit_config(config)
    batch_size = rate_config["batch_size"]
    rest_delay = rate_config["rest_delay"]
    jitter = rate_config["jitter"]
    max_retries = rate_config["max_retries"]
    
    all_symbols = tickers_to_add
    adj = pd.DataFrame()
    
    for batch, batch_num, total_batches in _batch_generator(all_symbols, batch_size):
        
        retry_count = 0
        while retry_count < max_retries:
            try:
                # yfinance's `end` is exclusive, so end on Jan 1 to include Dec 31.
                # Rate-limited tickers are retried, and the ones still failing
                # are left out of the file so the next run tries them again.
                batch_adj, batch_failed = download_prices(
                    batch, "Close", start=beginning_date, end=f"{current_year}-01-01", auto_adjust=True,
                )
                failed_tickers.extend(batch_failed)
                
                # Calculate returns for this batch immediately
                batch_yearly_data = {}
                for ticker in [t for t in batch if t not in batch_failed]:
                    if ticker not in batch_adj.columns:
                        no_data_tickers.append(ticker)
                        continue
                    
                    batch_yearly_data[ticker] = {}
                    ticker_has_data = False
                    
                    for year in range(beginning_date_dt.year, current_year):
                        year_start = pd.Timestamp(f"{year}-01-01")
                        year_end = pd.Timestamp(f"{year}-12-31")
                        
                        if year_end <= year_start:
                            continue
                        
                        try:
                            # Drop this ticker's blank rows (dates other tickers in the
                            # batch traded but it didn't, e.g. before a mid-year launch)
                            # so the year's first/last prices are its own.
                            ticker_adj = batch_adj[[ticker]].dropna()
                            year_return = make_return_series(ticker_adj, year_start, year_end)

                            if ticker in year_return.index and pd.notna(year_return[ticker]):
                                batch_yearly_data[ticker][str(year)] = year_return[ticker]
                                ticker_has_data = True
                        except Exception as e:
                            print(f"    Warning: Failed to calculate {year} return for {ticker}: {e}")
                    
                    if not ticker_has_data:
                        no_data_tickers.append(ticker)
                        del batch_yearly_data[ticker]
                
                # Merge batch results with yearly_data
                yearly_data.update(batch_yearly_data)
                
                # Merge with accumulated price data
                adj = pd.concat([adj, batch_adj], axis=1)
                
                print(f"    Calculated returns for batch {batch_num} ({len(batch_yearly_data)} tickers)")
                
                # Clear batch data from memory to save space
                del batch_yearly_data
                del batch_adj
                
                break
                
            except Exception as e:
                retry_count += 1
                if retry_count < max_retries:
                    wait_time = rest_delay + random.uniform(0, jitter)
                    print(f"    Retry {retry_count}/{max_retries} after error: {e}")
                    print(f"    Waiting {wait_time:.1f}s...")
                    time.sleep(wait_time)
                else:
                    print(f"    Failed to download batch {batch_num} after {max_retries} retries: {e}")
                    failed_tickers.extend(batch)
        
        # Rate limiting delay between batches (except last batch)
        if batch_num < total_batches:
            wait_time = rest_delay + random.uniform(0, jitter)
            print(f"  Waiting {wait_time:.1f}s before next batch...")
            time.sleep(wait_time)
    
    # Convert yearly_data to DataFrame and merge with existing cache. Funds
    # with no complete year get an empty row (not already cached).
    new_df = pd.DataFrame.from_dict(yearly_data, orient='index')
    empty_rows = sorted(set(no_data_tickers) - set(cached_df.index) - set(new_df.index))
    if empty_rows:
        new_df = pd.concat([new_df, pd.DataFrame(index=empty_rows, columns=new_df.columns, dtype="float64")])
    
    if len(new_df.index):  # rows with no year columns still count (empty rows)
        if not cached_df.empty:
            # Append new data to existing cache. Retried empty rows that now
            # have data are replaced; everything else is preserved.
            refilled = [t for t in new_df.index if t in cached_df.index]
            if refilled:
                print(f"Filled {len(refilled)} previously empty tickers")
            final_merged = pd.concat([cached_df.drop(index=refilled), new_df])
        else:
            final_merged = new_df
        
        save_yearly_history_csv(cache_path, final_merged)
        print(f"Processing complete. {len(yearly_data)} tickers with returns, {len(empty_rows)} saved empty (no complete year on Yahoo)")
        print(f"Total tickers in cache: {len(final_merged)}")
    else:
        print("No valid data to save.")
    added = list(yearly_data)
    
    if failed_tickers:
        print(f"Download failed for {len(failed_tickers)} ticker(s); they will be tried again next run.")
    
    # Clear large data structures from memory
    del adj
    del yearly_data
    
    if no_data_tickers:
        shown = sorted(set(no_data_tickers))
        print(f"No complete year on Yahoo for {len(shown)} ticker(s): {', '.join(shown[:20])}{' ...' if len(shown) > 20 else ''}")
    return added


if __name__ == "__main__":
    print("Adding any missing completed years for cached tickers...")
    add_missing_years(DEFAULT_CONFIG)
    print("\nRetrying cached tickers with no data yet (e.g. funds launched last year)...")
    build_yearly_history_cache(DEFAULT_CONFIG, tickers=(), retry_empty=True)
    print("\nDone!")
