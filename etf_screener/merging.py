"""
Merging structural + performance data, filtering to ETFs and Mutual Funds,
and attaching calendar-year returns.
"""

import os
from typing import Any, Dict, List, Tuple

import pandas as pd


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


def attach_yearly_returns(
    df: pd.DataFrame, csv_path: str, n_years: int = 10
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Left-join the most recent `n_years` calendar-year returns from the
    yearly history CSV (tickers as index, one column per year, returns as
    fractions) onto df by Ticker.

    Columns are named "Yearly Return (YYYY)" and converted to percent to
    match Morningstar's "Total Return (...)" columns, and placed right after
    the last Total Return column. If the CSV is missing, df is returned
    unchanged with a warning so the screener still runs.

    Also returns a report of funds with no yearly return in the window,
    printed to the terminal and saved in run_recorder.yaml:
      - launched_after_<last year>: inception after the last complete
        year, so no value is expected yet
      - not_in_yearly_file: ticker absent from the CSV (add it to
        yahoo_returns/sources/tickers.txt)
      - no_data_in_yearly_file: ticker in the CSV but every year is empty
    """
    if not os.path.exists(csv_path):
        print(f"  Warning: yearly returns file not found ({csv_path}) -- skipping yearly return columns.")
        return df, {"error": f"yearly returns file not found: {csv_path}"}

    yearly: pd.DataFrame = pd.read_csv(csv_path, index_col=0)
    year_cols: List[str] = sorted((c for c in yearly.columns if str(c).isdigit()), key=int)[-n_years:]
    yearly = yearly[year_cols] * 100.0
    yearly.index = yearly.index.astype(str).str.strip().str.upper()
    yearly = yearly[~yearly.index.duplicated(keep="last")]
    yearly.columns = [f"Yearly Return ({y})" for y in year_cols]

    keys = df["Ticker"].astype(str).str.strip().str.upper()
    attached = yearly.reindex(keys)
    attached.index = df.index
    new_cols: List[str] = list(attached.columns)

    out = df.drop(columns=[c for c in new_cols if c in df.columns])
    total_return_cols = [c for c in out.columns if str(c).startswith("Total Return (")]
    insert_at = out.columns.get_loc(total_return_cols[-1]) + 1 if total_return_cols else len(out.columns)
    out = pd.concat([out.iloc[:, :insert_at], attached, out.iloc[:, insert_at:]], axis=1)

    # --- Report funds with no yearly return in the window ---
    last_year = int(year_cols[-1])
    has_value = attached.notna().any(axis=1)
    in_file = keys.isin(yearly.index)
    if "Inception Date" in df.columns:
        inception = pd.to_datetime(df["Inception Date"], errors="coerce")
        too_new = inception > pd.Timestamp(f"{last_year}-12-31")
    else:
        too_new = pd.Series(False, index=df.index)

    def _tickers(mask: pd.Series) -> List[str]:
        return sorted(set(keys[mask]))

    new_key = f"launched_after_{last_year}"
    report: Dict[str, Any] = {
        "years": f"{year_cols[0]}-{year_cols[-1]}",
        "funds_with_values": int(has_value.sum()),
        "funds_total": len(df),
        new_key: _tickers(~has_value & too_new),
        "not_in_yearly_file": _tickers(~has_value & ~too_new & ~in_file),
        "no_data_in_yearly_file": _tickers(~has_value & ~too_new & in_file),
    }

    print(f"  Yearly returns {report['years']} attached for {report['funds_with_values']}/{len(df)} funds.")
    labels = {
        new_key: f"launched after {last_year} (expected, no full year yet)",
        "not_in_yearly_file": "not in yearly file (add to yahoo_returns/sources/tickers.txt, then run yahoo_returns/yearly_cache_manager.py)",
        "no_data_in_yearly_file": "in yearly file but no data",
    }
    for k, label in labels.items():
        if report[k]:
            print(f"    Missing - {label}: {len(report[k])}")
            print(f"      {', '.join(report[k])}")

    return out, report
