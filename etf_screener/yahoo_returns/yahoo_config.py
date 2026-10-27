"""
Configuration for Yahoo Finance historical data downloader.

This module contains default settings for the user_defined_by_date_yahoo_analize script,
including rate limiting, caching, and input/output paths.

All paths are absolute, built from this folder (etf_screener/yahoo_returns/),
so the scripts work no matter which directory they are run from.
"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent          # etf_screener/yahoo_returns
SOURCES_DIR = BASE_DIR / "sources"                  # the returns caches
REPO_DIR = BASE_DIR.parent.parent                   # ETF-Fund-Screener

# Default benchmark indexes for comparison
DEFAULT_INDEXES = ["^IXIC", "^DJI", "^GSPC"]

# Rate limiting settings to avoid Yahoo Finance API limits
DEFAULT_RATE_LIMITING = {
    "batch_size": 50,                    # Number of tickers per batch
    "rest_delay_seconds": 10.0,          # Delay between batches
    "rest_delay_jitter_seconds": 10.0,    # Random jitter to add to delay
    "max_download_retries": 3,           # Max retries for failed downloads
}

# Caching settings for price history data
DEFAULT_CACHING = {
    "enable_cache": True,                # Enable/disable caching
    "cache_path": str(BASE_DIR / "cache" / "yahoo_price_cache.json"),  # Path to cache file
    "cache_max_age_days": 1,             # Cache validity period in days
    "yearly_returns_cache_path": str(SOURCES_DIR / "etf_yearly_history.csv"),  # Yearly returns cache (CSV)
    "yearly_returns_max_age_days": 30,   # Yearly returns cache validity
    "history_start_date": "2006-01-01",  # Always start history from this date
}

# Default input/output paths
DEFAULT_PATHS = {
    "sources_dir": str(SOURCES_DIR),                       # cache files
    "default_output_dir": str(REPO_DIR / "output" / "yahoo_screen"),    # User-defined script output when using the default input
    "screener_output_dir": str(REPO_DIR / "output" / "etf_screener"),  # ETF screener results; latest results_*.xlsx is the user-defined default input
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
    "query": DEFAULT_QUERY,
}
