"""
ETF Fund Screener - project-wide settings.

Everything that belongs to ONE profile (filters, weights, top_n, folders)
lives only in that profile's YAML in input_files/ -- see input_file.py.
This file holds what every profile shares: the eTrade columns to load,
the Yahoo return caches, benchmark indexes, letter-grade mappings and
how many reports to keep. (Yahoo download settings are the defaults of
utils/yahoo_metrics.YahooMetricsConfig.)

IMPORTANT NOTE ABOUT COLUMN NAMES:
  The NEEDED_COLS list below must match the EXACT
  column headers in your Morningstar Excel files. Any mismatch (extra spaces,
  (R)/(TM) symbols, different capitalization) will cause those columns to be
  silently dropped. If you see warnings about missing columns at runtime,
  check your Excel file headers and update these lists to match exactly.
"""

from pathlib import Path
from typing import List, Optional

# Reports kept in the output folder. After each run, older reports (with
# their used-weights files, _by_category folders and run_recorder entries)
# are deleted. None = keep everything.
KEEP_LAST_REPORTS: Optional[int] = 10

# Purchase rules for EVERY profile: funds that break one are removed right
# after loading (before Yahoo downloads and scoring), so no profile sees
# them. A blank value passes (e.g. ETFs have no minimum investment).
# None = no limit for that rule.
PURCHASE_RULES = {
    "max_front_load": 0.0,             # percent: sales charge when buying ("Maximum Front Load")
    "max_deferred_load": 0.0,          # percent: sales charge when selling ("Maximum Deferred Load")
    "max_redemption_fee": 0.0,         # percent: fee for selling soon after buying ("Redemption Fee")
    "min_initial_investment": 50_000,  # dollars: funds needing MORE to start are removed ("Minimum Initial Investment")
}

# Calendar-year returns maintained by yahoo_returns/yearly_cache_manager.py:
# each screener run adds new funds, the January GitHub job adds the finished
# year. The most recent N years are attached to the screener output as
# "Yearly Return (YYYY)" columns, in percent like Morningstar's Total Return
# columns; their Yearly Beat % / Bottom 10% stats feed the Resilience score.
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
    "Dividend per Share (Trailing Annual)",
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
