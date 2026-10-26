"""
Extra report tab written next to the main sheet in the results workbook.

(The former Top / Bottom 50 1W & 1M momentum tabs are now saved queries:
python db_access/query.py momentum_top / momentum_bottom.)

No Yahoo data: funds Yahoo returned no price history for (no Sharpe or
Z-score at all) are moved off the overview into their own tab, with a
column in front listing which Yahoo-based results are missing.
"""

from typing import Dict, List, Tuple

import pandas as pd

NO_YAHOO_TAB = "No Yahoo Data"

YAHOO_PRICE_COLS = ["Sharpe 1y", "Sharpe 3y", "Z Score 1y", "Z Score 3y"]


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
