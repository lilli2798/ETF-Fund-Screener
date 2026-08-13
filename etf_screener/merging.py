"""
Merging structural + performance data, and filtering to ETFs and Mutual Funds.
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


def apply_fund_filter(df: pd.DataFrame) -> pd.DataFrame:
    """
    Keep only ETFs and Mutual Funds, excluding individual stocks.

    Logic:
    - Stocks: Share Class Type is null → excluded
    - ETFs and Mutual Funds: Share Class Type is not null → kept
    """
    filtered: pd.DataFrame = df.copy()
    start_count: int = len(filtered)
    print(f"Fund filter (ETFs + Mutual Funds): start count = {start_count}")

    has_share_class_col: bool = "Share Class Type" in filtered.columns

    # Debug: show Share Class Type values
    if has_share_class_col:
        print(f"  Share Class Type unique values: {filtered['Share Class Type'].unique()[:10]}")
    else:
        print(f"  Share Class Type column not found in data")

    if has_share_class_col:
        # Keep rows where Share Class Type is not null (excludes stocks)
        # This includes both ETFs and Mutual Funds
        is_fund: pd.Series = filtered["Share Class Type"].notna()
    else:
        # Fallback: if Share Class Type is missing, keep rows with fund-level data
        has_expense_col: bool = "Net Expense Ratio" in filtered.columns
        has_fund_size_col: bool = "Fund Size" in filtered.columns
        if has_expense_col and has_fund_size_col:
            is_fund: pd.Series = (
                filtered["Net Expense Ratio"].notna() & filtered["Fund Size"].notna()
            )
        else:
            # If no reliable columns, keep everything (warn user)
            print("  Warning: No reliable fund filter columns found, keeping all rows")
            is_fund = pd.Series(True, index=filtered.index)

    excluded: pd.DataFrame = filtered[~is_fund]
    filtered = filtered[is_fund]

    excluded_count: int = start_count - len(filtered)
    if excluded_count > 0:
        print(f"Fund filter: excluded {excluded_count} non-fund (stock) row(s).")
        if "Ticker" in excluded.columns:
            sample_tickers = excluded["Ticker"].dropna().astype(str).head(10).tolist()
            print(f"  Examples of excluded tickers: {sample_tickers}")

    print(f"Fund filter: {start_count} -> {len(filtered)} fund rows remain.")
    return filtered
