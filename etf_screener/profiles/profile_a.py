"""
Profile A: eligibility filter + composite scoring/ranking logic.

Self-registers into scoring.PROFILE_FILTERS / PROFILE_SCORERS under the
key "A" on import -- main.py just needs `import profiles.profile_a` once
and this profile becomes available via process_data(profile_name="A").

Updated to consume the new per-concept score columns produced by
scoring.build_concept_scores() (Performance_Score, Risk_Adjusted_Score,
Volatility_Score, Tracking_Score, Liquidity_Size_Score,
Quality_Valuation_Score, Costs_Score, Tax_Income_Score) instead of the
old flat Norm_* columns. Each of those concept scores is already
computed WITHIN Morningstar Category, so Profile A just applies a
second layer of weights across concepts -- it doesn't need to know
anything about the underlying raw metriåcs.

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

    These stay as hard gates on the RAW columns (not the concept
    scores), per the project decision that funds without a full 3-year
    history or fund size are excluded entirely, not scored on
    whatever shorter history they have.
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

    # Structural exclusions -- Profile A targets steady, long-term,
    # low-risk holdings, so leveraged/interval/tender-offer funds are
    # hard-excluded regardless of how well they score on the 8 weighted
    # concepts. These flag columns are built unscored by
    # scoring.build_structure_flags() (part of build_concept_scores()),
    # so they must already exist on `df` by the time this filter runs.
    exclude_leveraged_funds = thresholds.get("exclude_leveraged_funds", True)
    exclude_interval_funds = thresholds.get("exclude_interval_funds", True)
    exclude_tender_offer_funds = thresholds.get("exclude_tender_offer_funds", True)

    if exclude_leveraged_funds and "Flag_Leveraged_Fund" in eligible.columns:
        before = len(eligible)
        eligible = eligible[~eligible["Flag_Leveraged_Fund"].fillna(False)]
        print(f"  Profile A filter - exclude leveraged funds: {before} -> {len(eligible)}")

    if exclude_interval_funds and "Flag_Interval_Fund" in eligible.columns:
        before = len(eligible)
        eligible = eligible[~eligible["Flag_Interval_Fund"].fillna(False)]
        print(f"  Profile A filter - exclude interval funds: {before} -> {len(eligible)}")

    if exclude_tender_offer_funds and "Flag_Tender_Offer" in eligible.columns:
        before = len(eligible)
        eligible = eligible[~eligible["Flag_Tender_Offer"].fillna(False)]
        print(f"  Profile A filter - exclude tender-offer funds: {before} -> {len(eligible)}")

    print(f"Profile A eligibility filter: {start_count} -> {len(eligible)} rows remain.")
    return eligible


@register_profile_scorer("A")
def compute_profile_A_score(df: pd.DataFrame, top_n: int, thresholds: dict) -> pd.DataFrame:
    """
    Weights come from thresholds["weights"] in the input YAML if present,
    otherwise fall back to config.PROFILE_A_WEIGHTS. This blends the
    already-category-relative concept scores (each 0-100) into a single
    Profile_A_Score using Profile A's long-term/low-risk weighting
    philosophy: performance and risk-adjusted return matter most, costs
    and volatility next, other concepts lighter or zero by default.

    Expects df to already have gone through
    scoring.build_concept_scores(df) so the *_Score columns below exist.
    """
    scored: pd.DataFrame = df.copy()

    weights = thresholds.get("weights", PROFILE_A_WEIGHTS)

    weight_map = {
        "Performance_Score": weights.get("performance", 0.30),
        "Risk_Adjusted_Score": weights.get("risk_adjusted", 0.20),
        "Volatility_Score": weights.get("volatility", 0.15),
        "Tracking_Score": weights.get("tracking", 0.0),
        "Liquidity_Size_Score": weights.get("liquidity_size", 0.0),
        "Quality_Valuation_Score": weights.get("quality_valuation", 0.0),
        "Costs_Score": weights.get("costs", 0.15),
        "Tax_Income_Score": weights.get("tax_income", 0.0),
    }

    available_cols: List[str] = [c for c in weight_map if c in scored.columns]
    if not available_cols:
        raise ValueError(
            "compute_profile_A_score(): none of the expected concept-score "
            "columns are present. Did you run build_concept_scores() "
            "before calling this function?"
        )
    missing_cols = [c for c in weight_map if c not in scored.columns]
    if missing_cols:
        print(f"  Note: Profile A scoring proceeding without {missing_cols} "
              f"(concept score(s) not found) -- remaining weights re-normalized.")

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
