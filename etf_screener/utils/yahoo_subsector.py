"""Backward-compatible shim for legacy imports.

Sub-sector classification now lives in utils.yahoo_metrics alongside the
consolidated Yahoo Sharpe/Z-score pipeline. This module re-exports the
older sub-sector helpers so existing imports keep working.
"""
from .yahoo_metrics import (
    DEFAULT_SUBSECTOR,
    SECTOR_TAXONOMY,
    SUBSECTOR_KEYWORDS,
    YahooMetricsConfig,
    classify_holding_subsector,
    get_yahoo_metrics_for_tickers,
    read_tickers_from_file,
    resolve_ticker_subsector,
    unmapped_key_log,
)

__all__ = [
    "DEFAULT_SUBSECTOR",
    "SECTOR_TAXONOMY",
    "SUBSECTOR_KEYWORDS",
    "YahooMetricsConfig",
    "classify_holding_subsector",
    "get_yahoo_metrics_for_tickers",
    "read_tickers_from_file",
    "resolve_ticker_subsector",
    "unmapped_key_log",
]
