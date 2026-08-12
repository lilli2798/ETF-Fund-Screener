"""
ETF Fund Screener - Configuration File

This file contains all the default settings, weights, and thresholds used by
the screener. You typically don't need to edit this file directly - most
settings can be overridden in your YAML configuration file (e.g., input_profile_a.yaml).

IMPORTANT NOTE ABOUT COLUMN NAMES:
  The STRUCT_NEEDED_COLS and PERF_NEEDED_COLS lists below must match the EXACT
  column headers in your Morningstar Excel files. Any mismatch (extra spaces,
  (R)/(TM) symbols, different capitalization) will cause those columns to be
  silently dropped. If you see warnings about missing columns at runtime,
  check your Excel file headers and update these lists to match exactly.
"""

from typing import List

DEFAULT_TOP_N_PER_CATEGORY: int = 5

# Default input/output paths -- adjust to your environment, or override at
# runtime via get_paths_from_user() / CLI args.
DEFAULT_DATA_PATH: str = "data"
DEFAULT_OUT_PATH: str = "../output/etf_screener"

# Default profile to run when none is specified.
DEFAULT_PROFILE_NAME: str = "A"

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
    "Last Price", "Day Change (%)", "Day Change", "TTM Yield",
    "Total Return (1M)", "Total Return (2M)", "Total Return (3M)",
    "Total Return (6M)", "Total Return (9M)", "Total Return (YTD)",
    "Total Return (1Y)", "Total Return (2Y)", "Total Return (3Y)",
    "Total Return (4Y)", "Total Return (5Y)", "Total Return (10Y)",
    "Total Return (Since Inception)",
    "1M Return Rank in Category", "2M Return Rank in Category",
    "3M Return Rank in Category", "6M Return Rank in Category",
    "9M Return Rank in Category", "YTD Return Rank in Category",
    "1Y Return Rank in Category", "2Y Return Rank in Category",
    "3Y Return Rank in Category", "4Y Return Rank in Category",
    "5Y Return Rank in Category", "10Y Return Rank in Category",

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
    "Net Expense Ratio", "Adjusted Expense Ratio", "Management Fee",
    "Total Net Assets for Share Class", "Fund Size",
    "Premium/Discount", "Premium/Discount (1Y Avg)",
    "Portfolio Growth Grade", "Portfolio Financial Health Grade",
    "Portfolio Economic Moat Coverage (Wide)",
    "Portfolio Economic Moat Coverage (Narrow)",
    "Portfolio Economic Moat Coverage (None)",
    "Portfolio Return on Invested Capital", "Portfolio Price/Earnings",
    "Portfolio Price/Book", "Portfolio Price/Sales",
    "Portfolio Price/Free Cash Flow", "Portfolio Price/Fair Value",
    "ETF Fair Value", "Yield to Maturity", "Effective Duration",
    "Tracking Error (1Y Monthly)", "Tracking Error (3Y Monthly)",
    "Tracking Error (5Y Monthly)", "Tracking Error (10Y Monthly)",

    # Fund management and ratings
    "Fund Managers", "Number of Fund Managers", "Longest Manager Tenure",
    "Longest Tenured Manager", "Management Style",
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
    "Dividend per Share (Forward Annual)", "TTM Yield",

    # Fund flags
    "Leveraged Fund", "Interval Fund", "Fund of Funds",
    "Investment Status", "Strategic Beta Group",
    "Share Class Type", "Tender Offer", "Index Fund", "No Load Fund",
    "Enhanced Index Fund",

    # ESG columns (new in Morningstar format)
    "Portfolio Corporate ESG Risk Score",
    "Portfolio Environmental Risk Score",
    "Portfolio Social Risk Score",
    "Portfolio Governance Risk Score",
    "Portfolio Carbon Risk Score",
    "Portfolio ESG Risk Rating",
    "Sustainable Investment",
]

# Weights used by Profile A's composite score. Exposed here (rather than
# hardcoded in scoring.py) so future profiles can reuse the same knobs
# with different weightings, and so you can tune Profile A without
# touching scoring logic.
#
# NOTE: these keys map to scoring.py's per-CONCEPT scores (each already
# 0-100 and category-relative), not to individual raw metrics anymore.
# See profiles/profile_a.py::compute_profile_A_score() for the mapping:
#   performance        -> Performance_Score
#   risk_adjusted       -> Risk_Adjusted_Score
#   volatility          -> Volatility_Score      (lower vol/drawdown is better -- inverted in scoring)
#   tracking            -> Tracking_Score         (lower tracking error is better -- inverted in scoring)
#   liquidity_size       -> Liquidity_Size_Score
#   quality_valuation    -> Quality_Valuation_Score
#   costs               -> Costs_Score            (lower cost is better -- inverted in scoring)
#   tax_income          -> Tax_Income_Score
PROFILE_A_WEIGHTS = {
    "performance": 0.25,
    "risk_adjusted": 0.20,
    "volatility": 0.15,
    "tracking": 0.05,
    "liquidity_size": 0.05,
    "quality_valuation": 0.10,
    "costs": 0.15,
    "tax_income": 0.05,
}

# Morningstar's recommended long-term investment criteria weights.
# Based on Morningstar's guidance for long-term ETF selection:
# - 5Y Return: 25%
# - 10Y Return: 20%
# - 3Y Sharpe: 20%
# - Drawdown: 15%
# - Expense: 10%
# - Quality: 10%
MORNINGSTAR_LONG_TERM_WEIGHTS = {
    "performance": 0.45,  # Combined 5Y (25%) + 10Y (20%) = 45%
    "risk_adjusted": 0.20,  # 3Y Sharpe: 20%
    "volatility": 0.15,  # Drawdown: 15%
    "quality_valuation": 0.10,  # Quality: 10%
    "costs": 0.10,  # Expense: 10%
    "tracking": 0.00,  # Not used in Morningstar's criteria
    "liquidity_size": 0.00,  # Not used in Morningstar's criteria
    "tax_income": 0.00,  # Not used in Morningstar's criteria
}

# Column-level weights INSIDE each concept function (e.g. how much
# Total Return 3Y vs 5Y counts within Performance_Score). These are
# separate from PROFILE_A_WEIGHTS above, which controls how much each
# whole CONCEPT counts relative to the other concepts.
#
# This is the canonical default schema for `thresholds.concept_weights`
# in the profile input YAML -- while you're still learning what each
# column means and tuning weights, you can override just one or two
# leaf values in the YAML (e.g. concept_weights.performance.return_3y)
# and everything else here still applies via deep_merge_dicts().
DEFAULT_CONCEPT_WEIGHTS = {
    "performance": {
        "return_10y": 0.00,     # 10-year returns (optional for long-term focus)
        "return_5y": 0.35,
        "return_3y": 0.40,
        "return_1y": 0.10,
        "rank_3y": 0.15,
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
    },
    "volatility": {
        "stdev_3y": 0.45,
        "drawdown_3y": 0.30,
        "drawdown_5y": 0.25,
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
        "growth_grade": 0.25,
        "financial_health": 0.25,
        "price_fair_value": 0.20,
        "medalist": 0.15,   # NEW — raise/lower as you like; use 0.0 to ignore
        "economic_moat_wide": 0.15,  # NEW — Portfolio Economic Moat Coverage (Wide)
    },
    "costs": {
        "net_expense_ratio": 0.75,
        "management_fee": 0.25,
    },
    "tax_income": {
        "tax_cost_ratio": 0.55,
        "sec_yield": 0.45,
    },
}

# Morningstar's recommended concept weights for long-term investing.
# Emphasizes 5Y/10Y returns, 3Y Sharpe, drawdown, expense ratio, and quality.
MORNINGSTAR_CONCEPT_WEIGHTS = {
    "performance": {
        "return_5y": 0.56,  # 25% / 45% = 55.6% of performance weight
        "return_10y": 0.44,  # 20% / 45% = 44.4% of performance weight
        "return_3y": 0.00,   # Not emphasized in Morningstar's criteria
        "return_1y": 0.00,   # Not emphasized for long-term
        "rank_3y": 0.00,     # Not used
    },
    "risk_adjusted": {
        "sharpe_3y": 1.00,  # 100% on 3Y Sharpe per Morningstar's criteria
        "sharpe_1y": 0.00,   # Not used
        "upside": 0.00,      # Not used
        "downside": 0.00,    # Not used
        "yahoo_sharpe_3y": 0.00,  # Not used
        "yahoo_sharpe_1y": 0.00,  # Not used
        "yahoo_zscore_3y": 0.00,  # Not used
        "yahoo_zscore_1y": 0.00,  # Not used
    },
    "volatility": {
        "stdev_3y": 0.00,   # Not used - drawdown is the key metric
        "drawdown_3y": 0.50,  # 3Y drawdown (50% of volatility weight)
        "drawdown_5y": 0.50,  # 5Y drawdown (50% of volatility weight)
    },
    "tracking": {
        "tracking_error_3y": 0.00,  # Not used in Morningstar's criteria
        "tracking_error_1y": 0.00,  # Not used
    },
    "liquidity_size": {
        "fund_size": 0.00,    # Not used
        "trading_volume": 0.00,  # Not used
    },
    "quality_valuation": {
        "growth_grade": 0.30,      # Growth grade (40% of quality weight)
        "financial_health": 0.20,  # Financial health (40% of quality weight)
        "price_fair_value": 0.15,  # Price vs fair value (20% of quality weight)
        "medalist": 0.15,           # Not explicitly mentioned
        "economic_moat_wide": 0.20,  # Not explicitly mentioned
    },
    "costs": {
        "net_expense_ratio": 1.00,  # 100% on expense ratio per Morningstar's criteria
        "management_fee": 0.00,     # Not used
    },
    "tax_income": {
        "tax_cost_ratio": 0.00,  # Not used
        "sec_yield": 0.00,       # Not used
    },
}

DEFAULT_YAHOO_METRICS = {
    "batch_size": 50,
    "rest_delay_seconds": 60.0,
    "rest_delay_jitter_seconds": 10.0,
    "sample_stock_lookups": 5,
    "max_download_retries": 3,
    "risk_free_annual": 0.04,
    "price_history_period": "3y",
    "log_unmapped_keys": True,
    "subsector_cache_path": "utils/sector_cache.json",
    "subsector_cache_max_age_days": 30,
    "force_refresh_subsector": False,
    "checkpoint_path": "utils/yahoo_checkpoint.json",
    "enable_resume": True,
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

    # Profile-level concept weights (how much each concept counts).
    "weights": PROFILE_A_WEIGHTS,

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
