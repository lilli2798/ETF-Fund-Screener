"""
Shared configuration and constants for the ETF screener pipeline.

Edit STRUCT_NEEDED_COLS / PERF_NEEDED_COLS to match the EXACT header text
in your source Excel files. Any mismatch (trailing space, (R)/(TM) symbol,
naming variant) will be silently dropped by pandas' usecols -- this is the
bug we traced earlier, and data_loading.read_and_concat_excels() now prints
a warning at runtime if a requested name doesn't exactly match the file's
real header row.
"""

from typing import List

DEFAULT_TOP_N_PER_CATEGORY: int = 5

# Default input/output paths -- adjust to your environment, or override at
# runtime via get_paths_from_user() / CLI args.
DEFAULT_STRUCT_PATH: str = "python-etfs.xlsx"
DEFAULT_PERF_PATH: str = "performance-etfs.xlsx"
DEFAULT_OUT_PATH: str = "output"

# Default profile to run when none is specified.
DEFAULT_PROFILE_NAME: str = "A"

# --- Structural data columns (python-etfs.xlsx) ------------------------
# TODO: replace with your exact column list if this differs from what
# we've seen in this conversation's uploaded files. Leaving this as None
# tells pandas to load ALL columns (safe default, no silent drops) --
# set an explicit list here only once you've confirmed exact header text.
STRUCT_NEEDED_COLS: List[str] = [
    "Ticker", "Morningstar Category", "Exchange", "Exchange Country",
    "Sharpe Ratio (1Y Monthly)", "Sharpe Ratio (3Y Monthly)",
    "Worst Three Month Return", "Portfolio Risk Score",
    "Tracking Error (1Y Monthly)", "Tracking Error (3Y Monthly)",
    "Primary Benchmark", "Net Expense Ratio", "Adjusted Expense Ratio",
    "Management Fee", "Total Net Assets for Share Class", "Fund Size",
    "Trading Volume", "Premium/Discount", "Trading Status",
    "Portfolio Growth Grade", "Portfolio Financial Health Grade",
    "Portfolio Economic Moat Coverage (Wide)",
    "Portfolio Return on Invested Capital", "Portfolio Price/Earnings",
    "Portfolio Price/Book", "Portfolio Price/Sales",
    "Portfolio Price/Free Cash Flow", "Portfolio Price/Fair Value",
    "ETF Fair Value", "Fund Managers", "Number of Fund Managers",
    "Longest Manager Tenure", "Longest Tenured Manager",
    "Management Style", "Medalist Rating (Overall)",
    "Tax Cost Ratio (1Y)", "Tax Cost Ratio (2Y)",
    "Potential Capital Gains Exposure", "SEC 30-Day Yield",
    "Leveraged Fund", "Interval Fund", "Fund of Funds",
    "Investment Status", "Strategic Beta Group",
    "Share Class Type", "Tender Offer", "Inception Date",
]

# --- Performance data columns (performance-etfs.xlsx) ------------------
# TODO: replace with your exact column list -- same caution as above.
PERF_NEEDED_COLS: List[str] = [
    "Ticker", "Name", "Last Price", "Day Change (%)",
    "Equity Style Box (Funds)", "Asset Class", "TTM Yield",
    "Total Return (1M)", "Total Return (3M)", "Total Return (6M)",
    "Total Return (YTD)", "Total Return (1Y)", "Total Return (3Y)",
    "Total Return (5Y)", "Total Return (10Y)",
    "Total Return (Since Inception)",
    "1Y Return Rank in Category", "3Y Return Rank in Category",
    "5Y Return Rank in Category", "10Y Return Rank in Category",
    "Morningstar Risk Rating (Overall)", "Morningstar Risk Rating (3Y)",
    "Morningstar Rating for Funds (Overall)",
    "Morningstar Rating for Funds (3Y)",
    "Standard Deviation (3Y Monthly)", "Upside Capture Ratio (3Y)",
    "Downside Capture Ratio (3Y)", "Maximum Drawdown (3Y)",
    "Maximum Drawdown (5Y)", "Index Fund", "No Load Fund",
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
        "return_3y": 0.40,
        "return_5y": 0.35,
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
        "growth_grade": 0.35,
        "financial_health": 0.35,
        "price_fair_value": 0.30,
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

DEFAULT_YAHOO_METRICS = {
    "batch_size": 20,
    "rest_delay_seconds": 3.5,
    "sample_stock_lookups": 5,
    "max_download_retries": 3,
    "risk_free_annual": 0.04,
    "price_history_period": "3y",
    "log_unmapped_keys": True,
    "subsector_cache_path": "utils/sector_cache.json",
    "subsector_cache_max_age_days": 30,
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
