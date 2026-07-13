"""
Shared scoring logic (concept scores used by every profile) plus a
profile registry so new profiles can be added without editing this file
or main.py.
"""

from typing import Callable, Dict, Optional
import pandas as pd

from config import GRADE_TO_NUMERIC

# --- Profile registry -------------------------------------------------
# Each profile module (e.g. profiles/profile_a.py) registers its own
# eligibility-filter function and scoring function here via the
# decorators below. main.py never needs to know how many profiles exist
# or what their names are -- it just looks them up by profile_name.

PROFILE_FILTERS: Dict[str, Callable[[pd.DataFrame, dict], pd.DataFrame]] = {}
PROFILE_SCORERS: Dict[str, Callable[[pd.DataFrame, int, dict], pd.DataFrame]] = {}


def register_profile_filter(name: str):
    """Decorator: register a DataFrame -> DataFrame eligibility filter under `name`."""
    def deco(fn):
        if name in PROFILE_FILTERS:
            print(f"Warning: overwriting existing profile filter registered under '{name}'.")
        PROFILE_FILTERS[name] = fn
        return fn
    return deco


def register_profile_scorer(name: str):
    """Decorator: register a (DataFrame, top_n) -> DataFrame scorer under `name`."""
    def deco(fn):
        if name in PROFILE_SCORERS:
            print(f"Warning: overwriting existing profile scorer registered under '{name}'.")
        PROFILE_SCORERS[name] = fn
        return fn
    return deco


def _grade_to_numeric(value) -> Optional[float]:
    """Map a Morningstar letter grade (e.g. 'B+') to a numeric score via GRADE_TO_NUMERIC."""
    if pd.isna(value):
        return None
    key = str(value).strip().upper()
    return GRADE_TO_NUMERIC.get(key)


def _min_max_normalize(series: pd.Series, invert: bool = False) -> pd.Series:
    """
    Normalize a numeric Series to 0-1 range using min-max scaling.
    If `invert` is True, lower raw values map to HIGHER normalized scores
    (useful for "lower is better" metrics like expense ratio or risk score).
    Missing values are left as NaN (callers should decide how to treat
    NaN -- typically excluded from composite averaging, not zero-filled,
    so a missing metric doesn't unfairly tank a fund's score).
    """
    numeric: pd.Series = pd.to_numeric(series, errors="coerce")
    lo, hi = numeric.min(), numeric.max()
    if pd.isna(lo) or pd.isna(hi) or hi == lo:
        # No spread to normalize against -- return all-NaN so this metric
        # is excluded from composite scoring rather than distorting it.
        return pd.Series([float("nan")] * len(numeric), index=numeric.index)
    normalized: pd.Series = (numeric - lo) / (hi - lo)
    return (1 - normalized) if invert else normalized


def build_concept_scores(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build shared "concept" scores/features used across all profiles, before
    any profile-specific filtering or ranking happens. Adding a column here
    once makes it available to every current and future profile.

    Adds (when source columns are present):
      - Growth_Grade_Numeric, Financial_Health_Grade_Numeric
          (from Portfolio Growth/Financial Health Grade letter columns)
      - Norm_Return_3Y, Norm_Return_5Y, Norm_Sharpe_3Y
          (0-1 normalized, higher is better)
      - Norm_Expense_Ratio, Norm_Risk_Score
          (0-1 normalized and INVERTED, since lower expense/risk is better)

    Missing source columns are skipped gracefully (no KeyError) so this
    function works even if a data source doesn't have every field --
    downstream profile scorers should check for column presence before
    depending on any of these.
    """
    out: pd.DataFrame = df.copy()

    if "Portfolio Growth Grade" in out.columns:
        out["Growth_Grade_Numeric"] = out["Portfolio Growth Grade"].apply(_grade_to_numeric)

    if "Portfolio Financial Health Grade" in out.columns:
        out["Financial_Health_Grade_Numeric"] = out["Portfolio Financial Health Grade"].apply(_grade_to_numeric)

    if "Total Return (3Y)" in out.columns:
        out["Norm_Return_3Y"] = _min_max_normalize(out["Total Return (3Y)"])

    if "Total Return (5Y)" in out.columns:
        out["Norm_Return_5Y"] = _min_max_normalize(out["Total Return (5Y)"])

    if "Sharpe Ratio (3Y Monthly)" in out.columns:
        out["Norm_Sharpe_3Y"] = _min_max_normalize(out["Sharpe Ratio (3Y Monthly)"])

    if "Net Expense Ratio" in out.columns:
        out["Norm_Expense_Ratio"] = _min_max_normalize(out["Net Expense Ratio"], invert=True)

    if "Risk_Score_Numeric" in out.columns:
        out["Norm_Risk_Score"] = _min_max_normalize(out["Risk_Score_Numeric"], invert=True)

    if "Tracking Error (3Y Monthly)" in out.columns:
        out["Norm_Tracking_Error_3Y"] = _min_max_normalize(out["Tracking Error (3Y Monthly)"], invert=True)

    if "Tracking Error (1Y Monthly)" in out.columns:
        out["Norm_Tracking_Error_1Y"] = _min_max_normalize(out["Tracking Error (1Y Monthly)"], invert=True)

    if "Morningstar Rating Overall" in out.columns:
        out["Norm_Star_Rating"] = _min_max_normalize(out["Morningstar Rating Overall"])

    if "Sharpe Ratio (1Y Monthly)" in out.columns:
        out["Norm_Sharpe_1Y"] = _min_max_normalize(out["Sharpe Ratio (1Y Monthly)"])

    if "Max Drawdown (3Y Monthly)" in out.columns:
        out["Norm_Max_Drawdown"] = _min_max_normalize(out["Max Drawdown (3Y Monthly)"], invert=True)

    if "Financial_Health_Grade_Numeric" in out.columns:
        out["Norm_Financial_Health"] = _min_max_normalize(out["Financial_Health_Grade_Numeric"])

    if "Growth_Grade_Numeric" in out.columns:
        out["Norm_Growth_Grade"] = _min_max_normalize(out["Growth_Grade_Numeric"])

    return out
