"""
Profile A: eligibility filter + composite scoring/ranking logic.

Self-registers into scoring.PROFILE_FILTERS / PROFILE_SCORERS under the
key "A" on import -- main.py just needs `import profiles.profile_a` once
and this profile becomes available via process_data(profile_name="A").

Updated to consume the per-concept score columns produced by
scoring.build_concept_scores() (Long_Term_Return_Performance_Score,
Short_Term_Return_Performance_Score, Risk_Adjusted_Score,
Volatility_Score, Tracking_Score, Liquidity_Size_Score,
Quality_Valuation_Score, Costs_Score, Tax_Income_Score) instead of the
old flat Norm_* columns. Each of those concept scores is already
computed WITHIN Morningstar Category, so Profile A just applies a
second layer of weights across concepts -- it doesn't need to know
anything about the underlying raw metrics.

Stage A rules (this profile):
  - Score ONLY numeric concept columns listed in weight_map.
  - Do NOT fold qualitative text fields (Medalist, letter grades,
    Risk Label, Management Style, Morningstar Risk Rating text) into
    Profile_A_Score. Those may exist on the frame for export/review only.
  - Profile_A_Score / rank columns are forced to plain float64 so Excel
    does not treat them as text.

To add a new profile in the future:
  1. Copy this file to profiles/profile_b.py (or whatever name you like).
  2. Rename the functions and the registered key (e.g. "B").
  3. Add one line `import profiles.profile_b` in main.py.
No other file needs to change.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add parent directory to path so imports work when running scripts directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import Dict, List

import numpy as np
import pandas as pd

from config import PROFILE_A_WEIGHTS
from scoring import register_profile_filter, register_profile_scorer


# Concept columns Profile A may weight. Anything not in this map is ignored
# by the composite (including qualitative text columns).
CONCEPT_WEIGHT_KEYS: Dict[str, str] = {
    "Long_Term_Return_Performance_Score": "long_term_return_performance",
    "Short_Term_Return_Performance_Score": "short_term_return_performance",
    "Risk_Adjusted_Score": "risk_adjusted",
    "Volatility_Score": "volatility",
    "Tracking_Score": "tracking",
    "Liquidity_Size_Score": "liquidity_size",
    "Quality_Valuation_Score": "quality_valuation",
    "Costs_Score": "costs",
    "Tax_Income_Score": "tax_income",
}


def _as_float_series(s: pd.Series) -> pd.Series:
    """Coerce to float64; invalid values -> NaN. Never leave object/str."""
    return pd.to_numeric(s, errors="coerce").astype("float64")


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
        # Ensure comparison is numeric even if loader left strings
        expense = _as_float_series(eligible["Net Expense Ratio"])
        # Only filter out funds with non-null expense ratio that exceeds threshold
        # Allow funds with NaN expense ratio to pass through
        eligible = eligible[expense.isna() | (expense <= float(max_expense_ratio))]
        print(
            f"  Profile A filter - expense ratio <= {max_expense_ratio}% (or NaN): "
            f"{before} -> {len(eligible)}"
        )

    if require_fund_size and "Fund Size" in eligible.columns:
        before = len(eligible)
        eligible = eligible[eligible["Fund Size"].notna()]
        print(f"  Profile A filter - fund size present: {before} -> {len(eligible)}")

    if require_3y_return and "Total Return (3Y)" in eligible.columns:
        before = len(eligible)
        ret3 = _as_float_series(eligible["Total Return (3Y)"])
        eligible = eligible[ret3.notna()]
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
        flag = eligible["Flag_Leveraged_Fund"].fillna(False).astype(bool)
        eligible = eligible[~flag]
        print(f"  Profile A filter - exclude leveraged funds: {before} -> {len(eligible)}")

    if exclude_interval_funds and "Flag_Interval_Fund" in eligible.columns:
        before = len(eligible)
        flag = eligible["Flag_Interval_Fund"].fillna(False).astype(bool)
        eligible = eligible[~flag]
        print(f"  Profile A filter - exclude interval funds: {before} -> {len(eligible)}")

    if exclude_tender_offer_funds and "Flag_Tender_Offer" in eligible.columns:
        before = len(eligible)
        flag = eligible["Flag_Tender_Offer"].fillna(False).astype(bool)
        eligible = eligible[~flag]
        print(f"  Profile A filter - exclude tender-offer funds: {before} -> {len(eligible)}")

    # Load and investment requirement filters
    max_deferred_load = thresholds.get("max_deferred_load", 0.0)
    max_front_load = thresholds.get("max_front_load", 0.0)
    min_initial_investment = thresholds.get("min_initial_investment", 50000)

    if max_deferred_load is not None and "Maximum Deferred Load" in eligible.columns:
        before = len(eligible)
        deferred_load = _as_float_series(eligible["Maximum Deferred Load"])
        # Only filter out funds with non-null deferred load that exceeds threshold
        # Allow funds with NaN deferred load to pass through
        eligible = eligible[deferred_load.isna() | (deferred_load <= float(max_deferred_load))]
        print(
            f"  Profile A filter - deferred load <= {max_deferred_load}% (or NaN): "
            f"{before} -> {len(eligible)}"
        )

    if max_front_load is not None and "Maximum Front Load" in eligible.columns:
        before = len(eligible)
        front_load = _as_float_series(eligible["Maximum Front Load"])
        # Only filter out funds with non-null front load that exceeds threshold
        # Allow funds with NaN front load to pass through
        eligible = eligible[front_load.isna() | (front_load <= float(max_front_load))]
        print(
            f"  Profile A filter - front load <= {max_front_load}% (or NaN): "
            f"{before} -> {len(eligible)}"
        )

    if min_initial_investment is not None and "Minimum Initial Investment" in eligible.columns:
        before = len(eligible)
        initial_inv = _as_float_series(eligible["Minimum Initial Investment"])
        # Only filter out funds with non-null initial investment that exceeds threshold
        # Allow funds with NaN initial investment to pass through
        eligible = eligible[initial_inv.isna() | (initial_inv <= float(min_initial_investment))]
        print(
            f"  Profile A filter - initial investment <= ${min_initial_investment:,} (or NaN): "
            f"{before} -> {len(eligible)}"
        )

    max_redemption_fee = thresholds.get("max_redemption_fee", 0.0)

    if max_redemption_fee is not None and "Redemption Fee" in eligible.columns:
        before = len(eligible)
        redemption_fee = _as_float_series(eligible["Redemption Fee"])
        # Only filter out funds with non-null redemption fee that exceeds threshold
        # Allow funds with NaN redemption fee to pass through
        eligible = eligible[redemption_fee.isna() | (redemption_fee <= float(max_redemption_fee))]
        print(
            f"  Profile A filter - redemption fee <= {max_redemption_fee}% (or NaN): "
            f"{before} -> {len(eligible)}"
        )

    # Historical benchmark performance filter
    require_benchmark_outperformance = thresholds.get("require_benchmark_outperformance", False)
    min_benchmark_beat_pct = thresholds.get("min_benchmark_beat_pct", 50.0)

    if require_benchmark_outperformance and "Better %" in eligible.columns:
        before = len(eligible)
        better_pct = _as_float_series(eligible["Better %"])
        # Require funds to beat benchmarks in at least X% of available years
        # Allow funds with NaN benchmark data to pass through
        eligible = eligible[better_pct.isna() | (better_pct >= float(min_benchmark_beat_pct))]
        print(
            f"  Profile A filter - benchmark outperformance >= {min_benchmark_beat_pct}% (or NaN): "
            f"{before} -> {len(eligible)}"
        )

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

    Stage A: qualitative columns are never read here.
    """
    if thresholds is None:
        thresholds = {}

    scored: pd.DataFrame = df.copy()
    weights = thresholds.get("weights", PROFILE_A_WEIGHTS) or {}

    # Build weight_map: concept_col -> weight
    weight_map: Dict[str, float] = {}
    for concept_col, yaml_key in CONCEPT_WEIGHT_KEYS.items():
        weight_map[concept_col] = float(weights.get(yaml_key, 0.0))

    available_cols: List[str] = [c for c in weight_map if c in scored.columns]
    if not available_cols:
        raise ValueError(
            "compute_profile_A_score(): none of the expected concept-score "
            "columns are present. Did you run build_concept_scores() "
            "before calling this function?\n"
            f"Expected any of: {list(CONCEPT_WEIGHT_KEYS)}\n"
            f"Present columns sample: {list(scored.columns)[:40]}"
        )

    missing_cols = [c for c in weight_map if c not in scored.columns]
    if missing_cols:
        print(
            f"  Note: Profile A scoring proceeding without {missing_cols} "
            f"(concept score(s) not found) -- remaining weights re-normalized."
        )

    # Coerce concept scores to float64 before weighting (fixes str/object leaks)
    for col in available_cols:
        scored[col] = _as_float_series(scored[col])

    # Drop zero-weight concepts from the active set (cleaner + avoids noise)
    active_cols = [c for c in available_cols if weight_map[c] != 0.0]
    if not active_cols:
        # All weights zero or missing -- fall back to equal weight on available
        print(
            "  Warning: all Profile A concept weights are 0; "
            "using equal weights on available concept scores."
        )
        active_cols = list(available_cols)
        eq = 1.0 / len(active_cols)
        for c in active_cols:
            weight_map[c] = eq

    active_weights = np.array([weight_map[c] for c in active_cols], dtype="float64")
    concept_mat = scored[active_cols].to_numpy(dtype="float64", copy=True)

    # Per-row: ignore NaN concepts and renormalize remaining weights
    # score_i = sum(val_ij * w_j) / sum(w_j for j where val_ij is finite)
    finite_mask = np.isfinite(concept_mat)
    weighted_vals = np.where(finite_mask, concept_mat * active_weights, 0.0)
    weight_sums = np.where(finite_mask, active_weights, 0.0).sum(axis=1)

    with np.errstate(invalid="ignore", divide="ignore"):
        row_scores = weighted_vals.sum(axis=1) / weight_sums
    row_scores = np.where(weight_sums > 0.0, row_scores, np.nan)

    # ---- numeric score (never object / never string) ----
    scored["Profile_A_Score"] = pd.Series(row_scores, index=scored.index, dtype="float64")
    scored["Profile_A_Score"] = _as_float_series(scored["Profile_A_Score"]).round(6)

    # ---- ranks as float64 (Excel-friendly; still 1,2,3,...) ----
    if "Morningstar Category" in scored.columns:
        scored["Profile_A_Rank_In_Category"] = (
            scored.groupby("Morningstar Category", dropna=False)["Profile_A_Score"]
            .rank(method="min", ascending=False)
        )
    else:
        scored["Profile_A_Rank_In_Category"] = scored["Profile_A_Score"].rank(
            method="min", ascending=False
        )

    scored["Profile_A_Rank_In_Category"] = _as_float_series(
        scored["Profile_A_Rank_In_Category"]
    )

    scored["Profile_A_Selected_Flag"] = (
        scored["Profile_A_Rank_In_Category"].le(float(top_n)).fillna(False).astype(bool)
    )

    scored["Profile_A_Rank_Overall"] = scored["Profile_A_Score"].rank(
        method="min", ascending=False
    )
    scored["Profile_A_Rank_Overall"] = _as_float_series(scored["Profile_A_Rank_Overall"])

    scored["Profile_A_Selected_Overall_Flag"] = (
        scored["Profile_A_Rank_Overall"].le(float(top_n)).fillna(False).astype(bool)
    )

    # Console proof (helps catch str regression early)
    print(
        "  Profile A score dtypes: "
        f"Score={scored['Profile_A_Score'].dtype}, "
        f"RankInCat={scored['Profile_A_Rank_In_Category'].dtype}, "
        f"RankOverall={scored['Profile_A_Rank_Overall'].dtype}"
    )
    if str(scored["Profile_A_Score"].dtype) == "object":
        raise TypeError("Profile_A_Score is object/str after scoring -- aborting.")

    return scored
