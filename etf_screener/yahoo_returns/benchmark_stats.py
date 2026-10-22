"""
Benchmark comparison statistics shared by analyze_yearly_returns.py and
user_defined_by_date_yahoo_analize.py, so both report the same numbers.

All functions take a returns DataFrame with tickers as the index and one
column per period (a year, month, week, ...). Rows whose ticker is one of
`indexes` (e.g. ^GSPC, ^DJI, ^IXIC) are treated as benchmarks and excluded
from the fund statistics.
"""

from typing import List

import numpy as np
import pandas as pd

PERCENTILE_BUCKETS: List[str] = [
    "top_10%", "top_20%", "top_30%", "top_40%", "top_50%",
    "top_60%", "top_70%", "top_80%", "top_90%", "worse_10%",
]


def add_better_worst_stats(out_df: pd.DataFrame, return_df: pd.DataFrame, indexes: List[str]) -> pd.DataFrame:
    """Join per-fund counts of periods beating / trailing every benchmark.

    Adds:
      - better: periods where the fund beat the HIGHEST benchmark return
      - worst: periods where the fund trailed the LOWEST benchmark return
      - total_columns: number of periods
      - no_null_columns: periods where the fund has a return
      - better_% / worst_%: better / worst as a share of no_null_columns
      - better_worst_diff: better_% - worst_% (a share, so funds with
        different history lengths are comparable)
    """
    idx_return_df = return_df.loc[return_df.index.intersection(indexes)]
    ticker_return_df = return_df.drop(index=indexes, errors="ignore")

    highest_index = idx_return_df.max(axis=0)
    lowest_index = idx_return_df.min(axis=0)

    stats = pd.DataFrame(index=ticker_return_df.index)
    stats["better"] = ticker_return_df.gt(highest_index, axis=1).sum(axis=1)
    stats["worst"] = ticker_return_df.lt(lowest_index, axis=1).sum(axis=1)
    stats["total_columns"] = len(ticker_return_df.columns)
    stats["no_null_columns"] = ticker_return_df.count(axis=1)
    has_data = stats["no_null_columns"] > 0
    stats["better_%"] = np.where(has_data, stats["better"] / stats["no_null_columns"], np.nan)
    stats["worst_%"] = np.where(has_data, stats["worst"] / stats["no_null_columns"], np.nan)
    stats["better_worst_diff"] = stats["better_%"] - stats["worst_%"]

    return out_df.join(stats, how="left")


def add_percentile_bucket_counts(out_df: pd.DataFrame, return_df: pd.DataFrame, indexes: List[str]) -> pd.DataFrame:
    """Join, per fund, how many periods it finished in each 10% bucket.

    Each period is ranked across all funds that have a return for it
    (benchmarks excluded); top_10% = best tenth, worse_10% = worst tenth.
    """
    ticker_return_df = return_df.drop(index=indexes, errors="ignore")
    pct_rank = ticker_return_df.rank(axis=0, method="average", pct=True)

    bounds = [(0.90, 1.00), (0.80, 0.90), (0.70, 0.80), (0.60, 0.70), (0.50, 0.60),
              (0.40, 0.50), (0.30, 0.40), (0.20, 0.30), (0.10, 0.20)]

    stats = pd.DataFrame(index=ticker_return_df.index)
    for name, (lower, upper) in zip(PERCENTILE_BUCKETS, bounds):
        stats[name] = ((pct_rank > lower) & (pct_rank <= upper)).sum(axis=1)
    stats["worse_10%"] = (pct_rank <= 0.10).sum(axis=1)

    return out_df.join(stats, how="left")


def append_index_validation_rows(out_df: pd.DataFrame, return_df: pd.DataFrame, indexes: List[str]) -> pd.DataFrame:
    """Move the benchmark rows to the bottom, after a blank separator row."""
    idx_rows = return_df.loc[return_df.index.intersection(indexes)].copy()
    if idx_rows.empty:
        return out_df

    out_df = out_df.drop(index=indexes, errors="ignore")  # listed once, at the bottom
    idx_rows = idx_rows.reindex(columns=out_df.columns)
    blank = pd.DataFrame([[np.nan] * len(out_df.columns)], columns=out_df.columns, index=[""])
    return pd.concat([out_df, blank, idx_rows], axis=0)
