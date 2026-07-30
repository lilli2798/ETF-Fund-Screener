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

import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple

from config import DEFAULT_CONFIG
import yfinance as yf
import random
import time


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
                batch_data = yf.download(batch, start=start, end=end, progress=False)
                
                if batch_data.empty:
                    print(f"    No data returned for batch {batch_num}")
                    break
                
                # Handle different yfinance return formats
                if isinstance(batch_data.columns, pd.MultiIndex):
                    if "Adj Close" in batch_data.columns.get_level_values(0):
                        batch_adj = batch_data["Adj Close"].copy()
                    elif "Close" in batch_data.columns.get_level_values(0):
                        batch_adj = batch_data["Close"].copy()
                    else:
                        raise ValueError("Neither Adj Close nor Close found in download")
                else:
                    if "Adj Close" in batch_data.columns:
                        batch_adj = batch_data[["Adj Close"]].copy()
                    elif "Close" in batch_data.columns:
                        batch_adj = batch_data[["Close"]].copy()
                        batch_adj.columns = ["Adj Close"]
                    else:
                        raise ValueError("Neither Adj Close nor Close found in download")
                
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


def extract_tickers_from_xlsx(output_dir: str) -> List[str]:
    """Extract tickers from the most recent .xlsx file in the output directory.
    
    Args:
        output_dir: Directory path to search for .xlsx files
    
    Returns:
        List of ticker symbols extracted from the index column of the most recent .xlsx file.
        Returns empty list if no files found or extraction fails.
    """
    output_path = Path(output_dir)
    if not output_path.exists():
        return []
    
    xlsx_files = list(output_path.glob("*.xlsx"))
    if not xlsx_files:
        return []
    
    # Get the most recent file by modification time
    latest_file = max(xlsx_files, key=lambda f: f.stat().st_mtime)
    
    try:
        # Read the first sheet and get index as tickers
        xls = pd.ExcelFile(latest_file)
        df = pd.read_excel(latest_file, sheet_name=xls.sheet_names[0], index_col=0)
        df.index = df.index.astype(str)
        tickers = [t.strip().upper() for t in df.index.tolist() if t and str(t) != "NAN"]
        print(f"Extracted {len(tickers)} tickers from {latest_file.name}")
        return tickers
    except Exception as e:
        print(f"Error extracting tickers from {latest_file.name}: {e}")
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


def save_missing_data_report(failed_tickers: List[str], output_path: str = "sources/missing_data.csv") -> None:
    """Save failed tickers to a CSV report file.
    
    Args:
        failed_tickers: List of ticker symbols that failed to download
        output_path: Path to save the missing data report CSV
    
    Returns:
        None
    """
    if not failed_tickers:
        return
    
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    df = pd.DataFrame({"Ticker": failed_tickers, "Error": "No data found in Yahoo Finance"})
    df.to_csv(output_file, index=False)
    print(f"  Missing data report saved to {output_path}")


# =========================================================================
# MAIN CACHE BUILD FUNCTION
# =========================================================================

def build_yearly_history_cache(config: Dict = None) -> None:
    """Build yearly history cache from scratch or update existing cache.
    
    Args:
        config: Configuration dictionary containing paths and caching settings
    
    Returns:
        None
    
    Workflow:
        1. Read tickers from sources/tickers.txt
        2. If no tickers.txt, extract tickers from most recent .xlsx in ../etf_screener/output/
        3. Load existing cache if it exists
        4. Identify tickers that need to be added (not in existing cache)
        5. Download data from 2006-01-01 to previous year 12-31 for new tickers
        6. Calculate yearly returns for each complete year
        7. Merge with existing cache and save to sources/etf_yearly_history.csv
        8. Report failed tickers to sources/missing_data.csv
    
    Note: This function preserves existing cache data and only adds new tickers.
    """
    if config is None:
        config = DEFAULT_CONFIG
    
    paths_config = config.get("paths", {})
    tickers_file = paths_config.get("tickers_file", "sources/tickers.txt")
    screener_output_dir = paths_config.get("screener_output_dir", "../etf_screener/output")
    cache_config = config.get("caching", {})
    history_start_date = cache_config.get("history_start_date", "2006-01-01")
    cache_path = cache_config.get("yearly_returns_cache_path", "sources/etf_yearly_history.csv")
    
    # Step 1: Try to load tickers from tickers.txt
    tickers = load_tickers_from_file(tickers_file)
    
    # Step 2: If no tickers.txt, extract from xlsx
    if not tickers:
        print(f"No tickers.txt found, extracting from {screener_output_dir}...")
        tickers = extract_tickers_from_xlsx(screener_output_dir)
    
    if not tickers:
        print("No tickers found. Please create sources/tickers.txt or ensure output directory has .xlsx files.")
        return
    
    print(f"Found {len(tickers)} tickers in input...")
    
    # Step 3: Load existing cache to preserve existing data
    cached_df = load_yearly_history_csv(cache_path)
    
    if not cached_df.empty:
        print(f"Existing cache has {len(cached_df)} tickers")
        # Filter out tickers already in cache
        tickers_to_add = [t for t in tickers if t not in cached_df.index]
        print(f"Adding {len(tickers_to_add)} new tickers, preserving {len(cached_df)} existing tickers")
    else:
        print("No existing cache found, building from scratch...")
        tickers_to_add = tickers
    
    if not tickers_to_add:
        print("All tickers already in cache. No update needed.")
        return
    
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
                batch_data = yf.download(batch, start=beginning_date, end=ending_date, progress=False)
                
                if batch_data.empty:
                    print(f"    No data returned for batch {batch_num}")
                    break
                
                # Handle different yfinance return formats
                if isinstance(batch_data.columns, pd.MultiIndex):
                    if "Adj Close" in batch_data.columns.get_level_values(0):
                        batch_adj = batch_data["Adj Close"].copy()
                    elif "Close" in batch_data.columns.get_level_values(0):
                        batch_adj = batch_data["Close"].copy()
                    else:
                        raise ValueError("Neither Adj Close nor Close found in download")
                else:
                    if "Adj Close" in batch_data.columns:
                        batch_adj = batch_data[["Adj Close"]].copy()
                    elif "Close" in batch_data.columns:
                        batch_adj = batch_data[["Close"]].copy()
                        batch_adj.columns = ["Adj Close"]
                    else:
                        raise ValueError("Neither Adj Close nor Close found in download")
                
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
                            ticker_adj = batch_adj[[ticker]]
                            year_return = make_return_series(ticker_adj, year_start, year_end)
                            
                            if not year_return.empty and ticker in year_return.index:
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
        save_missing_data_report(tickers_to_add)
        return
    
    # Convert yearly_data to DataFrame and merge with existing cache
    new_df = pd.DataFrame.from_dict(yearly_data, orient='index')
    
    if not new_df.empty:
        if not cached_df.empty:
            final_merged = pd.concat([cached_df, new_df]).groupby(level=0).last()
        else:
            final_merged = new_df
        
        save_yearly_history_csv(cache_path, final_merged)
        print(f"Processing complete. Successfully processed {len(yearly_data)} tickers")
        print(f"Total tickers in cache: {len(final_merged)}")
    else:
        print("No valid data to save.")
    
    print(f"Failed tickers: {len(failed_tickers)}")
    
    # Clear large data structures from memory
    del adj
    del yearly_data
    
    # Step 7: Report failed tickers
    if failed_tickers:
        save_missing_data_report(failed_tickers)
        print(f"Failed to retrieve data for {len(failed_tickers)} tickers")


if __name__ == "__main__":
    print("Building yearly history cache...")
    build_yearly_history_cache(DEFAULT_CONFIG)
    print("\nDone!")
