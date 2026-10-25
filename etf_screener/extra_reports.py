"""
Extra report tabs written next to the main sheet in the results workbook.

Short-term momentum: the funds that rank near the top (or bottom) for BOTH
the last week and the last month, using the "Return Rank (1W)" and
"Return Rank (1M)" columns (rank 1 = highest return).

For the top tab, K is the smallest number of rows such that at least
`n` funds are within the top K by 1W rank AND within the top K by 1M rank;
the bottom tab does the same from the worst end. Every report column is
kept, with the cutoff and each fund's 1W / 1M position added in front.

No Yahoo data: funds Yahoo returned no price history for (no Sharpe or
Z-score at all) are moved off the overview into their own tab, with a
column in front listing which Yahoo-based results are missing.
"""

from typing import Dict, List, Tuple

import pandas as pd

RANK_1W = "Return Rank (1W)"
RANK_1M = "Return Rank (1M)"

TOP_TAB = "Top 50 - 1W & 1M Momentum"
BOTTOM_TAB = "Bottom 50 - 1W & 1M Laggards"
NO_YAHOO_TAB = "No Yahoo Data"

YAHOO_PRICE_COLS = ["Sharpe 1y", "Sharpe 3y", "Z Score 1y", "Z Score 3y"]


def _both_within(df: pd.DataFrame, n: int, best: bool) -> Tuple[pd.DataFrame, int]:
    """Funds within the first K rows for both 1W and 1M (smallest K giving
    at least n funds). Positions count from the best (best=True) or the
    worst (best=False) return; ties share a position."""
    ranked = df[df[RANK_1W].notna() & df[RANK_1M].notna()]
    if ranked.empty:
        return ranked.copy(), 0

    # rank 1 = highest return, so the best funds have the smallest rank
    pos_1w = ranked[RANK_1W].rank(method="min", ascending=best)
    pos_1m = ranked[RANK_1M].rank(method="min", ascending=best)

    k = min(n, len(ranked))
    while k < len(ranked) and ((pos_1w <= k) & (pos_1m <= k)).sum() < n:
        k += 1
    mask = (pos_1w <= k) & (pos_1m <= k)

    side = "Top" if best else "Bottom"
    out = ranked[mask].copy()
    out.insert(0, f"{side} Position 1M", pos_1m[mask].astype(int))
    out.insert(0, f"{side} Position 1W", pos_1w[mask].astype(int))
    out.insert(0, f"{side} K Cutoff (rows needed)", k)
    # Strongest in both first: average of the two positions, then 1W position
    out["_avg"] = (out[f"{side} Position 1W"] + out[f"{side} Position 1M"]) / 2
    out = out.sort_values(["_avg", f"{side} Position 1W"]).drop(columns="_avg")
    return out, k


def build_momentum_tabs(df: pd.DataFrame, n: int = 50) -> Dict[str, pd.DataFrame]:
    """Return {tab_name: DataFrame} for the top and bottom 1W & 1M funds.
    Returns {} if the report has no 1W / 1M return ranks."""
    if RANK_1W not in df.columns or RANK_1M not in df.columns:
        print(f"  Momentum tabs skipped: '{RANK_1W}' / '{RANK_1M}' not in the report.")
        return {}

    top, k_top = _both_within(df, n, best=True)
    bottom, k_bottom = _both_within(df, n, best=False)
    print(f"  {TOP_TAB}: {len(top)} funds in the top {k_top} rows for both 1W and 1M")
    print(f"  {BOTTOM_TAB}: {len(bottom)} funds in the bottom {k_bottom} rows for both 1W and 1M")
    return {TOP_TAB: top, BOTTOM_TAB: bottom}


def split_no_yahoo_data(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
    """Split off the funds Yahoo returned no price history for.
    Returns (overview without them, {NO_YAHOO_TAB: those funds})."""
    cols = [c for c in YAHOO_PRICE_COLS if c in df.columns]
    if not cols:
        print(f"  {NO_YAHOO_TAB} tab skipped: no Sharpe / Z-score columns in the report.")
        return df, {}

    no_data = df[cols].isna().all(axis=1)
    if "Ticker" in df.columns:
        tickers = df["Ticker"].astype("string")
        no_data &= tickers.notna() & ~tickers.str.startswith("^", na=False)  # fund rows only, not index rows
    tab = df[no_data].copy()

    other_sources = {
        "yearly returns": "Yearly Periods With Data",
        "volatile periods": "Volatile Periods With Data",
    }
    missing: List[pd.Series] = []
    for label, col in other_sources.items():
        if col in tab.columns:
            missing.append(tab[col].fillna(0).eq(0).map({True: f", {label}", False: ""}))
    text = pd.Series("Sharpe / Z-score", index=tab.index)
    for part in missing:
        text = text + part
    tab.insert(0, "Missing From Yahoo", text)

    print(f"  {NO_YAHOO_TAB}: {len(tab)} fund(s) moved off the overview (Yahoo returned no price history)")
    return df[~no_data], {NO_YAHOO_TAB: tab}
