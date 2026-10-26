"""
ETF Fund Screener - Configuration File

This file contains all the default settings, weights, and thresholds used by
the screener. You typically don't need to edit this file directly - most
settings can be overridden in your YAML configuration file (e.g., input_files/profile_long_term.yaml).

IMPORTANT NOTE ABOUT COLUMN NAMES:
  The STRUCT_NEEDED_COLS and PERF_NEEDED_COLS lists below must match the EXACT
  column headers in your Morningstar Excel files. Any mismatch (extra spaces,
  (R)/(TM) symbols, different capitalization) will cause those columns to be
  silently dropped. If you see warnings about missing columns at runtime,
  check your Excel file headers and update these lists to match exactly.
"""

from pathlib import Path
from typing import List, Optional

DEFAULT_TOP_N_PER_CATEGORY: int = 5
# How many funds get Selected Overall Flag = 1 (best across all categories).
# None = same as top_n_per_category. Set per profile with top_n_overall in the YAML.
DEFAULT_TOP_N_OVERALL: Optional[int] = None

# Default input/output paths -- adjust to your environment, or override at
# runtime via get_paths_from_user() / CLI args.
DEFAULT_DATA_PATH: str = "data"
DEFAULT_OUT_PATH: str = "../output/etf_screener"

# Default profile to run when none is specified.
DEFAULT_PROFILE_NAME: str = "LT"

# Profile YAMLs run_ci.py runs (in this order) and alerts.py reports on,
# relative to the etf_screener/ folder.
PROFILE_INPUT_FILES: list = [
    "input_files/profile_long_term.yaml",
    "input_files/profile_short_term.yaml",
]

# Calendar-year returns maintained by yahoo_returns/yearly_cache_manager.py
# (updated by the yearly GitHub workflow). The most recent N years are
# attached to the screener output as "Yearly Return (YYYY)" columns, in
# percent like Morningstar's Total Return columns. Display only -- not scored.
YAHOO_RETURNS_DIR: str = str(Path(__file__).resolve().parent / "yahoo_returns")
YEARLY_RETURNS_CSV: str = str(Path(YAHOO_RETURNS_DIR) / "sources" / "etf_yearly_history.csv")
YEARLY_RETURN_YEARS: int = 10

# Volatile market periods (S&P 500 >= 15% declines and volatility spikes since
# 1976) from yahoo_returns/volatile_config.yaml -- regenerate with
# yahoo_returns/volatile_periods.py. Each fund's return in every period is attached to the
# output ("Volatile Decline/Recovery: ..."); results are cached in
# VOLATILE_RETURNS_CSV so only new funds are downloaded on later runs.
VOLATILE_CONFIG_PATH: str = str(Path(YAHOO_RETURNS_DIR) / "volatile_config.yaml")
VOLATILE_RETURNS_CSV: str = str(Path(YAHOO_RETURNS_DIR) / "sources" / "etf_volatile_history.csv")
VOLATILE_DOWNLOAD = {
    "batch_size": 200,
    "rest_delay_seconds": 3.0,
    "jitter_seconds": 2.0,
    "max_retries": 3,
}

# Benchmarks for the "beat / trailed all indexes" stats.
BENCHMARK_INDEXES: List[str] = ["^IXIC", "^DJI", "^GSPC"]

# --- Combined data columns (new Morningstar format) ------------------
# All columns needed from the new Morningstar profile-based Excel files.
# These files contain both performance and structural data in a single file.
# Updated to match the new Morningstar column names from the 7-file profile format.
NEEDED_COLS: List[str] = [
    # Identifier columns
    "Ticker", "Name", "Morningstar Category", "Asset Class",
    "Primary Benchmark", "Equity Style Box (Funds)", "Inception Date",
    "Broad Category Group",

    # Performance metrics
    "TTM Yield",
    "Total Return (1W)", "Total Return (1M)", "Total Return (2M)", "Total Return (QTD)",
    "Total Return (3M)", "Total Return (6M)", "Total Return (9M)", "Total Return (YTD)",
    "Total Return (1Y)", "Total Return (2Y)", "Total Return (3Y)",
    "Total Return (4Y)", "Total Return (5Y)", "Total Return (6Y)",
    "Total Return (7Y)", "Total Return (8Y)", "Total Return (9Y)",
    "Total Return (10Y)", "Total Return (15Y)", "Total Return (20Y)",
    "Total Return (Since Inception)",

    # Risk metrics
    "Sharpe Ratio (1Y Monthly)", "Sharpe Ratio (3Y Monthly)",
    "Sharpe Ratio (5Y Monthly)", "Sharpe Ratio (10Y Monthly)",
    "Standard Deviation (1Y Monthly)", "Standard Deviation (3Y Monthly)",
    "Standard Deviation (5Y Monthly)", "Standard Deviation (10Y Monthly)",
    "Worst Three Month Return", "Best Three Month Return",
    "Morningstar Risk Rating (Overall)", "Morningstar Risk Rating (3Y)",
    "Morningstar Risk Rating (5Y)", "Morningstar Risk Rating (10Y)",
    "Upside Capture Ratio (1Y)", "Upside Capture Ratio (3Y)",
    "Upside Capture Ratio (5Y)", "Upside Capture Ratio (10Y)",
    "Downside Capture Ratio (1Y)", "Downside Capture Ratio (3Y)",
    "Downside Capture Ratio (5Y)", "Downside Capture Ratio (10Y)",
    "Maximum Drawdown (1Y)", "Maximum Drawdown (3Y)",
    "Maximum Drawdown (5Y)", "Maximum Drawdown (10Y)",
    "Portfolio Risk Score", "Beta (3Y Monthly)", "Alpha (3Y Monthly)",

    # Structural/fundamental fields
    "Net Expense Ratio", "Adjusted Expense Ratio",
    "Total Net Assets for Share Class", "Fund Size",
    "Premium/Discount", "Premium/Discount (1Y Avg)",
    "Portfolio Growth Grade", "Portfolio Financial Health Grade", "Portfolio Profitability Grade",
    "Portfolio Economic Moat Coverage (Wide)",
    "Portfolio Economic Moat Coverage (Narrow)",
    "Portfolio Economic Moat Coverage (None)",
    "Portfolio Return on Invested Capital", "Portfolio Price/Earnings",
    "Portfolio Price/Book", "Portfolio Price/Sales",
    "Portfolio Price/Free Cash Flow", "Portfolio Price/Fair Value",
    "ETF Fair Value",
    "Tracking Error (1Y Monthly)", "Tracking Error (3Y Monthly)",
    "Tracking Error (5Y Monthly)", "Tracking Error (10Y Monthly)",

    # Fund management and ratings
    "Fund Managers",
    "Medalist Rating (Overall)", "Medalist Rating (Parent)",
    "Medalist Rating (People)", "Medalist Rating (Process)",
    "Morningstar Rating for Funds (Overall)",
    "Morningstar Rating for Funds (3Y)",
    "Morningstar Rating for Funds (5Y)",
    "Morningstar Rating for Funds (10Y)",
    "Morningstar Return Rating (Overall)",
    "Morningstar Return Rating (3Y)",
    "Morningstar Return Rating (5Y)",
    "Morningstar Return Rating (10Y)",

    # Tax and income
    "Tax Cost Ratio (1Y)", "Tax Cost Ratio (2Y)",
    "Tax Cost Ratio (3Y)", "Tax Cost Ratio (5Y)",
    "Tax Cost Ratio (10Y)",
    "Potential Capital Gains Exposure", "SEC 30-Day Yield",
    "SEC 7-Day Yield", "Dividend per Share (Trailing Annual)",
    "Dividend per Share (Forward Annual)", "Dividend per Share (1Y Avg)",
    "Dividend per Share (3Y Avg)",

    # Fund flags
    "Leveraged Fund", "Interval Fund", "Fund of Funds",
    "Investment Status", "Strategic Beta Group",
    "Share Class Type", "Tender Offer", "Index Fund",

    # Load and investment requirements
    "Maximum Deferred Load", "Maximum Front Load", "Minimum Initial Investment",
    "Redemption Fee",
]

# Fallback profile-level weights, used when a profile YAML has no
# `weights:` section. Exposed here (rather than hardcoded in scoring.py)
# so profiles can reuse the same knobs with different weightings
# without touching scoring logic.
#
# NOTE: these keys map to scoring.py's per-CONCEPT scores (each already
# 0-100 and category-relative), not to individual raw metrics anymore.
# See profiles/weighted_profile.py::compute_score() for the mapping:
#   long_term_return_performance -> Long_Term_Return_Performance_Score
#   short_term_return_performance -> Short_Term_Return_Performance_Score
#   risk_adjusted       -> Risk_Adjusted_Score
#   volatility          -> Volatility_Score      (steadier is better: lower std dev, drawdown closer to 0)
#   resilience          -> Resilience_Score      (beat the indexes in calendar years and volatile periods)
#   tracking            -> Tracking_Score         (lower tracking error is better -- inverted in scoring)
#   liquidity_size       -> Liquidity_Size_Score
#   quality_valuation    -> Quality_Valuation_Score
#   costs               -> Costs_Score            (lower cost is better -- inverted in scoring)
#   tax_income          -> Tax_Income_Score
DEFAULT_PROFILE_WEIGHTS = {
    "long_term_return_performance": 0.25,
    "short_term_return_performance": 0.10,
    "risk_adjusted": 0.20,
    "volatility": 0.15,
    "resilience": 0.00,
    "tracking": 0.05,
    "liquidity_size": 0.05,
    "quality_valuation": 0.10,
    "costs": 0.10,
    "tax_income": 0.00,
}

# Column-level weights INSIDE each concept function (e.g. how much
# Total Return 3Y vs 5Y counts within Performance_Score). These are
# separate from DEFAULT_PROFILE_WEIGHTS above, which controls how much each
# whole CONCEPT counts relative to the other concepts.
#
# This is the canonical default schema for `thresholds.concept_weights`
# in the profile input YAML -- while you're still learning what each
# column means and tuning weights, you can override just one or two
# leaf values in the YAML (e.g. concept_weights.performance.return_3y)
# and everything else here still applies via deep_merge_dicts().
DEFAULT_CONCEPT_WEIGHTS = {
    "long_term_return_performance": {
        "return_1y": 0.0833,  # 1/12 ≈ 8.33%
        "return_2y": 0.0833,  # 1/12 ≈ 8.33%
        "return_3y": 0.0833,  # 1/12 ≈ 8.33%
        "return_4y": 0.0833,  # 1/12 ≈ 8.33%
        "return_5y": 0.0833,  # 1/12 ≈ 8.33%
        "return_6y": 0.0833,  # 1/12 ≈ 8.33%
        "return_7y": 0.0833,  # 1/12 ≈ 8.33%
        "return_8y": 0.0833,  # 1/12 ≈ 8.33%
        "return_9y": 0.0833,  # 1/12 ≈ 8.33%
        "return_10y": 0.0833,  # 1/12 ≈ 8.33%
        "return_15y": 0.0833,  # 1/12 ≈ 8.33%
        "return_20y": 0.0835,  # 1/12 ≈ 8.35% (adjusted to sum to 1.0)
    },
    "short_term_return_performance": {
        "return_1w": 0.125,  # 1/8 = 12.5%
        "return_1m": 0.125,  # 1/8 = 12.5%
        "return_2m": 0.125,  # 1/8 = 12.5%
        "return_qtd": 0.125,  # 1/8 = 12.5%
        "return_3m": 0.125,  # 1/8 = 12.5%
        "return_6m": 0.125,  # 1/8 = 12.5%
        "return_9m": 0.125,  # 1/8 = 12.5%
        "return_ytd": 0.125,  # 1/8 = 12.5%
    },
    "risk_adjusted": {
        "sharpe_3y": 0.1,
        "sharpe_1y": 0.1,
        "upside": 0.15,
        "downside": 0.15,
        "yahoo_sharpe_3y": 0.10,
        "yahoo_sharpe_1y": 0.15,
        "yahoo_zscore_3y": 0.10,
        "yahoo_zscore_1y": 0.15,
        # Other periods (0.0 = not used unless a profile YAML sets them)
        "sharpe_5y": 0.00,
        "sharpe_10y": 0.00,
        "upside_1y": 0.00,
        "upside_5y": 0.00,
        "upside_10y": 0.00,
        "downside_1y": 0.00,
        "downside_5y": 0.00,
        "downside_10y": 0.00,
    },
    "volatility": {
        "stdev_3y": 0.45,
        "drawdown_3y": 0.30,
        "drawdown_5y": 0.25,
        "stdev_1y": 0.00,
        "stdev_5y": 0.00,
        "stdev_10y": 0.00,
        "drawdown_1y": 0.00,
        "drawdown_10y": 0.00,
    },
    # Consistency & crash resilience (Resilience_Score). Concept weight is
    # 0 in DEFAULT_PROFILE_WEIGHTS, so it only counts when a profile YAML
    # gives `weights.resilience` a value.
    "resilience": {
        "yearly_beat_pct": 0.25,          # % of calendar years the fund beat all indexes
        "yearly_bottom_10_share": 0.15,   # share of years in the bottom 10% (lower is better)
        "volatile_beat_pct": 0.25,        # % of volatile periods the fund beat all indexes
        "volatile_bottom_10_share": 0.15, # share of volatile periods in the bottom 10% (lower is better)
        "worst_3m_return": 0.20,          # Worst Three Month Return (higher is better)
    },
    "tracking": {
        "tracking_error_3y": 0.65,
        "tracking_error_1y": 0.35,
    },
    "liquidity_size": {
        "fund_size": 0.60,
        "trading_volume": 0.40,
    },
    "quality_valuation": {
        "growth_grade": 0.20,
        "financial_health": 0.15,
        "profitability_grade": 0.15,  # Portfolio profitability grade (A-F)
        "price_fair_value": 0.15,
        "medalist": 0.15,  # NEW — raise/lower as you like; use 0.0 to ignore
        "star_rating": 0.15,  # NEW — Morningstar Rating for Funds (star rating)
        "economic_moat_wide": 0.05,  # NEW — Portfolio Economic Moat Coverage (Wide)
    },
    "costs": {
        "adjusted_expense_ratio": 1.0,
    },
    "tax_income": {
        "tax_cost_ratio_1y": 0.20,
        "tax_cost_ratio_2y": 0.15,
        "dividend_per_share_trailing": 0.10,
        "dividend_per_share_forward": 0.10,
        "dividend_per_share_1y_avg": 0.10,
        "dividend_per_share_3y_avg": 0.10,
        "sec_yield": 0.25,
    },
}

DEFAULT_YAHOO_METRICS = {
    "batch_size": 200,                 # tickers per price download
    "rest_delay_seconds": 3.0,         # pause between price downloads
    "rest_delay_jitter_seconds": 2.0,
    "subsector_workers": 4,            # parallel sub-sector lookups (lower it if Yahoo rate-limits)
    "sample_stock_lookups": 10,        # top holdings used for the sub-sector (Yahoo lists at most 10)
    "max_download_retries": 3,
    "risk_free_annual": 0.04,
    "price_history_period": "3y",
    "log_unmapped_keys": True,
    "subsector_cache_path": "utils/sector_cache.json",
    "subsector_cache_max_age_days": 365,  # re-check each fund about once a year (+0-29 days spread)
    "force_refresh_subsector": False,
}

# Full default `thresholds` schema for the profile input YAML. Any keys
# the user omits from their YAML fall back to these values via
# deep_merge_dicts() in input_file.py, and nested dicts (weights,
# concept_weights) are merged key-by-key rather than replaced wholesale
# -- so overriding one leaf value never silently drops its siblings.
DEFAULT_THRESHOLDS = {
    "require_category": True,
    "max_expense_ratio": 0.75,
    "require_fund_size": True,
    "min_fund_size": None,
    "require_3y_return": True,
    "min_3y_return": None,

    # Structural/flag exclusions (see scoring.build_structure_flags).
    "exclude_leveraged_funds": True,
    "exclude_interval_funds": True,
    "exclude_tender_offer_funds": True,

    # Load and investment requirement filters
    "max_deferred_load": 0.0,  # Maximum deferred load (0.0 = no load allowed)
    "max_front_load": 0.0,      # Maximum front load (0.0 = no load allowed)
    "min_initial_investment": 50000,  # Remove funds requiring a larger minimum initial investment ($)
    "max_redemption_fee": 0.0,  # Maximum redemption fee (0.0 = no fee allowed)

    # Benchmark filter (profiles/weighted_profile.apply_filters): keep funds
    # whose Yearly Beat % is at least min_benchmark_beat_pct (or unknown).
    "require_benchmark_outperformance": False,
    "min_benchmark_beat_pct": 50.0,

    # Profile-level concept weights (how much each concept counts).
    "weights": DEFAULT_PROFILE_WEIGHTS,

    # Column-level weights inside each concept (how much each raw
    # metric counts within its own concept score).
    "concept_weights": DEFAULT_CONCEPT_WEIGHTS,

    # Yahoo Finance fetch/runtime settings used by utils.yahoo_metrics.
    "yahoo_metrics": DEFAULT_YAHOO_METRICS,
}

# Grade-letter -> numeric mapping, shared by any profile that scores on
# Morningstar's Growth / Financial Health letter grades.
GRADE_TO_NUMERIC = {
    "A+": 12, "A": 11, "A-": 10,
    "B+": 9, "B": 8, "B-": 7,
    "C+": 6, "C": 5, "C-": 4,
    "D+": 3, "D": 2, "D-": 1,
    "F": 0,
}

# Medalist Rating (Overall) -> ordered numeric.
# normalize_within_category turns this into 0-100 within peer group.
# Do NOT merge into GRADE_TO_NUMERIC (different scale/meaning).
MEDALIST_TO_NUMERIC = {
    "GOLD": 5,
    "SILVER": 4,
    "BRONZE": 3,
    "NEUTRAL": 2,
    "NEGATIVE": 1,
}

# Morningstar Rating for Funds (star rating) -> ordered numeric.
# normalize_within_category turns this into 0-100 within peer group.
# Do NOT merge into MEDALIST_TO_NUMERIC (different scale/meaning).
STAR_RATING_TO_NUMERIC = {
    "5": 5,
    "4": 4,
    "3": 3,
    "2": 2,
    "1": 1,
}
