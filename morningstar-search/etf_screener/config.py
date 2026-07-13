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
    "Trading Volume", "Shares Outstanding", "Premium/Discount",
    "Premium/Discount (1Y Avg)", "Trading Status",
    "Portfolio Growth Grade", "Portfolio Financial Health Grade",
    "Portfolio Economic Moat Coverage (Wide)",
    "Portfolio Return on Invested Capital", "Portfolio Price/Earnings",
    "Portfolio Price/Book", "Portfolio Price/Sales",
    "Portfolio Price/Free Cash Flow", "Portfolio Price/Fair Value",
    "Price/Fair Value", "Fair Value", "ETF Fair Value", "Economic Moat",
    "Capital Allocation", "Fund Managers", "Number of Fund Managers",
    "Longest Manager Tenure", "Longest Tenured Manager",
    "Management Style", "Medalist Rating (Overall)",
    "Tax Cost Ratio (1Y)", "Tax Cost Ratio (2Y)",
    "Potential Capital Gains Exposure", "SEC 30-Day Yield",
    "SEC 7-Day Yield", "Total Distribution Rate (NAV)",
    "Leveraged Fund", "Interval Fund", "Fund of Funds",
    "Investment Status", "Total Leverage Ratio", "Strategic Beta Group",
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
PROFILE_A_WEIGHTS = {
    "return_3y": 0.30,
    "return_5y": 0.20,
    "sharpe_3y": 0.20,
    "expense_ratio": 0.15,   # lower is better -- inverted in scoring
    "risk_score": 0.15,      # lower is better -- inverted in scoring
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
