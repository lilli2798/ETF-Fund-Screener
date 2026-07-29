"""
Configuration for Yahoo Finance historical data downloader.

This module contains default settings for the user_defined_by_date_yahoo_analize script,
including rate limiting, caching, and input/output paths.
"""
from pathlib import Path

# Default benchmark indexes for comparison
DEFAULT_INDEXES = ["^IXIC", "^DJI", "^GSPC"]

# Rate limiting settings to avoid Yahoo Finance API limits
DEFAULT_RATE_LIMITING = {
    "batch_size": 50,                    # Number of tickers per batch
    "rest_delay_seconds": 30.0,          # Delay between batches
    "rest_delay_jitter_seconds": 5.0,    # Random jitter to add to delay
    "max_download_retries": 3,           # Max retries for failed downloads
}

# Caching settings for price history data
DEFAULT_CACHING = {
    "enable_cache": True,                # Enable/disable caching
    "cache_path": "cache/yahoo_price_cache.json",  # Path to cache file
    "cache_max_age_days": 1,             # Cache validity period in days
    "yearly_returns_cache_path": "sources/etf_yearly_history.csv",  # Path for yearly returns cache (CSV format)
    "yearly_returns_max_age_days": 30,   # Yearly returns cache validity
    "history_start_date": "2006-01-01",  # Always start history from this date
}

# Default input/output paths
DEFAULT_PATHS = {
    "sources_dir": "sources",              # Directory for tickers.txt and cache files
    "tickers_file": "sources/tickers.txt", # Path to tickers.txt file
    "default_input_dir": "../etf_screener/data/structural-data",  # Default directory to look for input files
    "default_output_dir": "output",       # Default directory for output files
    "screener_output_dir": "../etf_screener/output",  # ETF screener output directory for date extraction
    "report_path": "output/run_recorder.yaml",  # Path for run metadata
}

# Report/metadata settings
DEFAULT_REPORT = {
    "enable_report": True,               # Generate run metadata report
    "include_query_params": True,        # Include query parameters in report
    "include_timestamp": True,           # Include run timestamp
}

# Default query parameters (used when user doesn't provide input)
DEFAULT_QUERY = {
    "beginning_date": "2010-01-01",      # Default start date
    "ending_date": None,                 # None = use today's date
    "default_period": "year",             # Default analysis period
    "default_n": 10,                      # Default number of periods
}

# Full default configuration
DEFAULT_CONFIG = {
    "indexes": DEFAULT_INDEXES,
    "rate_limiting": DEFAULT_RATE_LIMITING,
    "caching": DEFAULT_CACHING,
    "paths": DEFAULT_PATHS,
    "report": DEFAULT_REPORT,
    "query": DEFAULT_QUERY,
}
