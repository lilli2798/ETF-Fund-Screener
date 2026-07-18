"""
Merging structural + performance data, and filtering to ETFs only.
"""

from typing import List
import pandas as pd


def merge_datasets(df_struct: pd.DataFrame, df_perf: pd.DataFrame) -> pd.DataFrame:
    """
    Merge structural + performance data on Ticker.

    If both frames happen to share a column name (other than Ticker), this
    coalesces the two versions into one clean column instead of leaving
    _x/_y duplicates behind -- prefers the performance-side value, falling
    back to the structural-side value if missing.
    """
    overlap: List[str] = [
        c for c in df_struct.columns
        if c in df_perf.columns and c != "Ticker"
    ]
    if overlap:
        print(f"Note: {len(overlap)} overlapping column(s) found between "
              f"structural and performance data: {overlap}")

    merged: pd.DataFrame = pd.merge(
        df_struct, df_perf,
        on="Ticker", how="inner",
        validate="one_to_one",
        suffixes=("_struct", "_perf"),
    )

    for col in overlap:
        struct_col, perf_col = f"{col}_struct", f"{col}_perf"
        if struct_col in merged.columns and perf_col in merged.columns:
            merged[col] = merged[perf_col].combine_first(merged[struct_col])
            merged.drop(columns=[struct_col, perf_col], inplace=True)

    unmatched: int = len(df_struct) - len(merged)
    if unmatched > 0:
        print(
            f"Note: {unmatched} ticker(s) from the structural data had no "
            f"matching row in the performance data and were dropped."
        )

    return merged


def apply_etf_only_filter(df: pd.DataFrame) -> pd.DataFrame:
    """
    Keep only true ETFs, excluding individual stocks that were included in
    the Morningstar export.

    Uses multiple signals, since a single column may be blank or unreliable
    for some rows:
      1. 'Share Class Type' == 'ETF' (Morningstar's direct classification) -
         strongest signal when present.
      2. 'Morningstar Category' is a recognized fund category (stocks
         usually have this blank, or show an equity sector/industry
         classification instead of a Morningstar fund category).
      3. Fund-level structural fields must be populated (Net Expense Ratio,
         Fund Size) - individual stocks don't have expense ratios or
         "fund size"; they'd be NaN for a stock row.

    A row is kept if it passes signal 1 when available, OR passes both
    signal 2 and signal 3 as a fallback when Share Class Type is missing
    or ambiguous.
    """
    filtered: pd.DataFrame = df.copy()
    start_count: int = len(filtered)

    has_share_class_col: bool = "Share Class Type" in filtered.columns
    has_expense_col: bool = "Net Expense Ratio" in filtered.columns
    has_fund_size_col: bool = "Fund Size" in filtered.columns

    if has_share_class_col:
        is_etf_flagged: pd.Series = (
            filtered["Share Class Type"].astype(str).str.strip().str.upper() == "ETF"
        )
    else:
        is_etf_flagged = pd.Series(False, index=filtered.index)

    if has_expense_col and has_fund_size_col:
        has_fund_level_data: pd.Series = (
            filtered["Net Expense Ratio"].notna() & filtered["Fund Size"].notna()
        )
    else:
        has_fund_level_data = pd.Series(True, index=filtered.index)

    keep_mask: pd.Series = is_etf_flagged | (~has_share_class_col & has_fund_level_data)
    if has_share_class_col:
        keep_mask = is_etf_flagged | (filtered["Share Class Type"].isna() & has_fund_level_data)

    excluded: pd.DataFrame = filtered[~keep_mask]
    filtered = filtered[keep_mask]

    excluded_count: int = start_count - len(filtered)
    if excluded_count > 0:
        print(f"ETF-only filter: excluded {excluded_count} non-ETF row(s).")
        if "Ticker" in excluded.columns:
            sample_tickers = excluded["Ticker"].dropna().astype(str).head(10).tolist()
            print(f"  Examples of excluded tickers: {sample_tickers}")

    print(f"ETF-only filter: {start_count} -> {len(filtered)} rows remain.")
    return filtered
