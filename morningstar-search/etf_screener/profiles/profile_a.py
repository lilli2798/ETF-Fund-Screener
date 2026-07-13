"""
Profile A: eligibility filter + composite scoring/ranking logic.

Self-registers into scoring.PROFILE_FILTERS / PROFILE_SCORERS under the
key "A" on import -- main.py just needs `import profiles.profile_a` once
and this profile becomes available via process_data(profile_name="A").

To add a new profile in the future:
  1. Copy this file to profiles/profile_b.py (or whatever name you like).
  2. Rename the functions and the registered key (e.g. "B").
  3. Add one line `import profiles.profile_b` in main.py.
No other file needs to change.
"""

from typing import List
import pandas as pd

from config import PROFILE_A_WEIGHTS
from scoring import register_profile_filter, register_profile_scorer


@register_profile_filter("A")
def apply_profile_A_filters(df: pd.DataFrame, thresholds: dict) -> pd.DataFrame:
    """
    Apply Profile A's eligibility rules using values from the input-file
    `thresholds` dict (falling back to config defaults if a key is
    missing, so older YAML files without the newer keys still work):
      - require_category (bool)
      - max_expense_ratio (float)
      - require_fund_size (bool)
      - require_3y_return (bool)
    """
    start_count: int = len(df)
    eligible: pd.DataFrame = df.copy()

    require_category = thresholds.get("require_category", True)
    max_expense_ratio = thresholds.get("max_expense_ratio", 0.75)
    require_fund_size = thresholds.get("require_fund_size", True)
    require_3y_return = thresholds.get("require_3y_return", True)

    if require_category and "Morningstar Category" in eligible.columns:
        before = len(eligible)
        eligible = eligible[eligible["Morningstar Category"].notna()]
        print(f"  Profile A filter - valid category: {before} -> {len(eligible)}")

    if max_expense_ratio is not None and "Net Expense Ratio" in eligible.columns:
        before = len(eligible)
        eligible = eligible[
            eligible["Net Expense Ratio"].notna() & (eligible["Net Expense Ratio"] <= max_expense_ratio)
        ]
        print(f"  Profile A filter - expense ratio <= {max_expense_ratio}%: {before} -> {len(eligible)}")

    if require_fund_size and "Fund Size" in eligible.columns:
        before = len(eligible)
        eligible = eligible[eligible["Fund Size"].notna()]
        print(f"  Profile A filter - fund size present: {before} -> {len(eligible)}")

    if require_3y_return and "Total Return (3Y)" in eligible.columns:
        before = len(eligible)
        eligible = eligible[eligible["Total Return (3Y)"].notna()]
        print(f"  Profile A filter - has 3Y track record: {before} -> {len(eligible)}")

    print(f"Profile A eligibility filter: {start_count} -> {len(eligible)} rows remain.")
    return eligible



@register_profile_scorer("A")
def compute_profile_A_score(df: pd.DataFrame, top_n: int, thresholds: dict) -> pd.DataFrame:
    """
    Weights come from thresholds["weights"] in the input YAML if present,
    otherwise fall back to config.PROFILE_A_WEIGHTS.
    """
    scored: pd.DataFrame = df.copy()

    weights = thresholds.get("weights", PROFILE_A_WEIGHTS)

    weight_map = {
        "Norm_Return_3Y": weights.get("return_3y", 0.30),
        "Norm_Return_5Y": weights.get("return_5y", 0.20),
        "Norm_Sharpe_3Y": weights.get("sharpe_3y", 0.20),
        "Norm_Sharpe_1Y": weights.get("sharpe_1y", 0.0),
        "Norm_Expense_Ratio": weights.get("expense_ratio", 0.15),
        "Norm_Risk_Score": weights.get("risk_score", 0.15),
        "Norm_Tracking_Error_3Y": weights.get("tracking_error_3y", 0.0),
        "Norm_Tracking_Error_1Y": weights.get("tracking_error_1y", 0.0),
        "Norm_Max_Drawdown": weights.get("max_drawdown", 0.0),
        "Norm_Financial_Health": weights.get("financial_health", 0.0),
        "Norm_Growth_Grade": weights.get("growth_grade", 0.0),
        "Norm_Star_Rating": weights.get("star_rating", 0.0),
    }

    available_cols: List[str] = [c for c in weight_map if c in scored.columns]
    if not available_cols:
        raise ValueError(
            "compute_profile_A_score(): none of the expected normalized "
            "concept-score columns are present. Did you run "
            "build_concept_scores() before calling this function?"
        )
    missing_cols = [c for c in weight_map if c not in scored.columns]
    if missing_cols:
        print(f"  Note: Profile A scoring proceeding without {missing_cols} "
              f"(source column(s) not found) -- remaining weights re-normalized.")

    def weighted_row_score(row: pd.Series) -> float:
        total_weight: float = 0.0
        weighted_sum: float = 0.0
        for col in available_cols:
            val = row[col]
            if pd.notna(val):
                w = weight_map[col]
                weighted_sum += val * w
                total_weight += w
        if total_weight == 0.0:
            return float("nan")
        return weighted_sum / total_weight

    scored["Profile_A_Score"] = scored[available_cols].apply(weighted_row_score, axis=1)

    # Rank within category (1 = best). method='min' means ties share the
    # same rank rather than an arbitrary tiebreak order.
    if "Morningstar Category" in scored.columns:
        scored["Profile_A_Rank_In_Category"] = (
            scored.groupby("Morningstar Category")["Profile_A_Score"]
            .rank(method="min", ascending=False)
            .astype("Int64")
        )
    else:
        # No category column -- everything is effectively one big "category".
        scored["Profile_A_Rank_In_Category"] = (
            scored["Profile_A_Score"].rank(method="min", ascending=False).astype("Int64")
        )

    scored["Profile_A_Selected_Flag"] = scored["Profile_A_Rank_In_Category"] <= top_n

    scored["Profile_A_Rank_Overall"] = (
        scored["Profile_A_Score"].rank(method="min", ascending=False).astype("Int64")
    )
    scored["Profile_A_Selected_Overall_Flag"] = scored["Profile_A_Rank_Overall"] <= top_n

    return scored
