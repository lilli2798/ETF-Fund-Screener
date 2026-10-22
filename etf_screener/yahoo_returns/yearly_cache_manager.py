"""
Yearly History Cache Manager

This module manages the yearly returns cache for ETF tickers.
It provides functions to build, update, and load the cache from a CSV file.

The cache stores yearly returns for each ticker from 2006-01-01 to the previous year.
This is separate from the interactive analysis which may only need short-term returns.

Usage:
    # Build cache from scratch or update with new tickers
    python yearly_cache_manager.py

    # Or import and use programmatically
    from yearly_cache_manager import build_yearly_history_cache
    build_yearly_history_cache(config)
"""

import random
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import yfinance as yf

from yahoo_config import DEFAULT_CONFIG, SOURCES_DIR


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

def _extract_adjusted_close(batch_data: pd.DataFrame, batch: List[str]) -> pd.DataFrame:
    """Return dividend/split-adjusted closes (tickers as columns) from a
    yf.download(..., auto_adjust=True) result.

    With auto_adjust=True the adjusted price is in "Close". Don't look for
    "Adj Close" first: yfinance adds an "Adj Close" column only for tickers
    that FAILED (e.g. delisted), so picking it would drop every good ticker
    in the batch.
    """
    if isinstance(batch_data.columns, pd.MultiIndex):
        if "Close" not in batch_data.columns.get_level_values(0):
            raise ValueError("Close not found in download")
        return batch_data["Close"].copy()
    if "Close" not in batch_data.columns:
        raise ValueError("Close not found in download")
    single = batch_data[["Close"]].copy()
    single.columns = [batch[0]] if len(batch) == 1 else ["Close"]
    return single


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
                batch_data = yf.download(batch, start=start, end=end, auto_adjust=True, progress=False)
                
                if batch_data.empty:
                    print(f"    No data returned for batch {batch_num}")
                    break
                
                batch_adj = _extract_adjusted_close(batch_data, batch)
                
                # Handle single ticker case (Series vs DataFrame)
                if isinstance(batch_adj, pd.Series):
                    batch_adj = batch_adj.to_frame()
                
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
# TICKER LOADING FUNCTIONS
# =========================================================================

def load_tickers_from_file(tickers_file: str) -> List[str]:
    """Load tickers from tickers.txt file.
    
    Args:
        tickers_file: Path to the tickers.txt file
    
    Returns:
        List of ticker symbols (uppercase, stripped, non-NAN).
        Returns empty list if file doesn't exist or fails to load.
    """
    if not Path(tickers_file).exists():
        return []
    try:
        with open(tickers_file, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f.readlines()]
        return [x.strip().upper() for x in lines if x and x != "NAN"]
    except Exception:
        return []


# =========================================================================
# CACHE UPDATE FUNCTIONS
# =========================================================================

def update_cache_for_new_tickers(new_tickers: List[str], config: Dict = None) -> Tuple[pd.DataFrame, List[str]]:
    """Update CSV cache with new tickers by downloading their historical data.
    
    Args:
        new_tickers: List of ticker symbols to add to the cache
        config: Configuration dictionary containing caching settings
    
    Returns:
        Tuple of (updated_cache_df, list_of_failed_tickers)
        - updated_cache_df: DataFrame with all tickers (existing + new) and their yearly returns
        - failed_tickers: List of tickers that failed to download or had no data
    """
    if config is None:
        config = DEFAULT_CONFIG
    
    cache_config = config.get("caching", {})
    enable_cache = cache_config.get("enable_cache", True)
    cache_path = cache_config.get("yearly_returns_cache_path", "sources/etf_yearly_history.csv")
    history_start_date = cache_config.get("history_start_date", "2006-01-01")
    
    if not enable_cache:
        print("  Cache is disabled, skipping update.")
        return pd.DataFrame(), []
    
    # Load existing CSV cache
    cached_df = load_yearly_history_csv(cache_path)
    
    # Filter out tickers that are already in cache
    tickers_to_add = [t for t in new_tickers if cached_df.empty or t not in cached_df.index]
    
    if not tickers_to_add:
        print("  All tickers already in cache, no update needed.")
        return cached_df, []
    
    print(f"  Adding {len(tickers_to_add)} new tickers to cache...")
    
    # Always use history start date to previous year 12-31
    beginning_date = history_start_date
    current_year = datetime.now().year
    previous_year = current_year - 1
    ending_date = f"{previous_year}-12-31"
    
    # Download price data for new tickers
    failed_tickers = []
    try:
        adj = download_adj_close(tickers_to_add, beginning_date, ending_date, config)
        
        if adj.empty:
            print("  No data downloaded for new tickers.")
            return cached_df, tickers_to_add
        
        # Calculate yearly returns for new tickers
        beginning_date_dt = to_date(beginning_date)
        ending_date_dt = to_date(ending_date)
        
        yearly_data = {}
        
        for ticker in tickers_to_add:
            if ticker not in adj.columns:
                failed_tickers.append(ticker)
                continue
            
            yearly_data[ticker] = {}
            ticker_has_data = False
            
            for year in range(beginning_date_dt.year, current_year):
                year_start = pd.Timestamp(f"{year}-01-01")
                year_end = pd.Timestamp(f"{year}-12-31")
                
                if year_end <= year_start:
                    continue
                
                try:
                    ticker_adj = adj[[ticker]]
                    year_return = make_return_series(ticker_adj, year_start, year_end)
                    
                    if not year_return.empty and ticker in year_return.index:
                        yearly_data[ticker][str(year)] = year_return[ticker]
                        ticker_has_data = True
                except Exception as e:
                    print(f"    Warning: Failed to calculate {year} return for {ticker}: {e}")
            
            if not ticker_has_data:
                failed_tickers.append(ticker)
                del yearly_data[ticker]
        
        # Convert to DataFrame and merge with existing cache
        new_df = pd.DataFrame.from_dict(yearly_data, orient='index')
        merged_df = cached_df  # Initialize with existing cache
        
        if not new_df.empty:
            if not cached_df.empty:
                merged_df = pd.concat([cached_df, new_df]).groupby(level=0).last()
            else:
                merged_df = new_df
            
            save_yearly_history_csv(cache_path, merged_df)
            print(f"  Cache updated with {len(tickers_to_add) - len(failed_tickers)} new tickers")
        
        return merged_df, failed_tickers
        
    except Exception as e:
        print(f"  Error updating cache for new tickers: {e}")
        return cached_df, tickers_to_add


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

def build_yearly_history_cache(config: Dict = None) -> List[str]:
    """Build yearly history cache from scratch or update existing cache.
    
    Args:
        config: Configuration dictionary containing paths and caching settings
    
    Returns:
        Tickers whose rows were added or refilled (have data now).
    
    Workflow:
        1. Read tickers to add from sources/tickers.txt (may list only new ones)
        2. Load existing cache if it exists
        3. Identify tickers to download: not in the cache, or cached with no data
        4. Download data from 2006-01-01 to previous year 12-31 for new tickers
        5. Calculate yearly returns for each complete year
        6. Merge with existing cache and save to sources/etf_yearly_history.csv
        7. Print tickers Yahoo had no data for
    
    Note: This function preserves existing cache data. It adds new tickers and
    retries tickers whose cached row is entirely empty.
    """
    if config is None:
        config = DEFAULT_CONFIG
    
    paths_config = config.get("paths", {})
    tickers_file = paths_config.get("tickers_file", "sources/tickers.txt")
    cache_config = config.get("caching", {})
    history_start_date = cache_config.get("history_start_date", "2006-01-01")
    cache_path = cache_config.get("yearly_returns_cache_path", "sources/etf_yearly_history.csv")
    
    # Step 1: tickers.txt lists tickers to ADD -- it can hold just the new
    # ones. Tickers already in the cache are skipped, and cached tickers that
    # aren't listed are kept.
    tickers = load_tickers_from_file(tickers_file)
    print(f"Found {len(tickers)} tickers in {tickers_file}")
    
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
        # Retry every cached ticker with no data, listed in tickers.txt or not
        empty_tickers = set(cached_df.index[cached_df.isna().all(axis=1)])
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
    failed_tickers = []
    
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
                batch_data = yf.download(batch, start=beginning_date, end=f"{current_year}-01-01", auto_adjust=True, progress=False)
                
                if batch_data.empty:
                    print(f"    No data returned for batch {batch_num}")
                    break
                
                batch_adj = _extract_adjusted_close(batch_data, batch)
                
                # Handle single ticker case (Series vs DataFrame)
                if isinstance(batch_adj, pd.Series):
                    batch_adj = batch_adj.to_frame()
                
                # Calculate returns for this batch immediately
                batch_yearly_data = {}
                for ticker in batch:
                    if ticker not in batch_adj.columns:
                        failed_tickers.append(ticker)
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
                        failed_tickers.append(ticker)
                        del batch_yearly_data[ticker]
                
                # Merge batch results with yearly_data
                yearly_data.update(batch_yearly_data)
                
                # Merge with accumulated price data
                adj = pd.concat([adj, batch_adj], axis=1)
                
                print(f"    Calculated returns for batch {batch_num} ({len(batch_yearly_data)} tickers)")
                
                # Clear batch data from memory to save space
                del batch_yearly_data
                del batch_adj
                del batch_data
                
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
    
    if adj.empty:
        print("No data downloaded. All tickers failed.")
        return []
    
    # Convert yearly_data to DataFrame and merge with existing cache
    new_df = pd.DataFrame.from_dict(yearly_data, orient='index')
    
    if not new_df.empty:
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
        print(f"Processing complete. Successfully processed {len(yearly_data)} tickers")
        print(f"Total tickers in cache: {len(final_merged)}")
    else:
        print("No valid data to save.")
    added = list(new_df.index)
    
    print(f"Failed tickers: {len(failed_tickers)}")
    
    # Clear large data structures from memory
    del adj
    del yearly_data
    
    if failed_tickers:
        print(f"No Yahoo data for: {', '.join(sorted(set(failed_tickers)))}")
    return added


if __name__ == "__main__":
    from analyze_yearly_returns import add_tickers_to_analysis, analyze_yearly_returns

    print("Adding any missing completed years for cached tickers...")
    years_added = add_missing_years(DEFAULT_CONFIG)
    print("\nAdding any new tickers from tickers.txt...")
    tickers_added = build_yearly_history_cache(DEFAULT_CONFIG)

    csv_path = DEFAULT_CONFIG["caching"]["yearly_returns_cache_path"]
    report = DEFAULT_CONFIG["paths"]["yearly_analysis_path"]
    if years_added or not Path(report).exists():
        # A new year changes every fund's row -> rebuild the whole report
        print("\nRebuilding the yearly analysis report...")
        analyze_yearly_returns(csv_path, report)
    elif tickers_added:
        print(f"\nAdding {len(tickers_added)} ticker(s) to the yearly analysis report...")
        add_tickers_to_analysis(csv_path, tickers_added, report)
    else:
        print("\nNo changes -- yearly analysis report left as is.")
    print("\nDone!")
