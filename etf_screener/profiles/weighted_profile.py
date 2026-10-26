"""
Weighted profiles: eligibility filters + composite scoring/ranking logic
shared by every profile whose behaviour is set entirely by its YAML file.

Registered profiles (see PROFILE_KEYS at the bottom):
  - "LT"  input_files/profile_long_term.yaml   long-term, low-risk buy list
  - "ST"  input_files/profile_short_term.yaml  short-term momentum buy list

Each key gets its own prefilter, filter and scorer in
scoring.PROFILE_PREFILTERS / PROFILE_FILTERS / PROFILE_SCORERS when this
module is imported, plus its own output columns (Profile_LT_Score,
Profile_ST_Score, ...). Run together, the profiles share one report
(results_profile_LT_ST_...). The YAML's `profile:` value picks the key.

The scorer consumes the per-concept score columns produced by
scoring.build_concept_scores() (Long_Term_Return_Performance_Score,
Short_Term_Return_Performance_Score, Risk_Adjusted_Score,
Volatility_Score, Resilience_Score, Tracking_Score, Liquidity_Size_Score,
Quality_Valuation_Score, Costs_Score, Tax_Income_Score). Each of those
concept scores is already computed WITHIN Morningstar Category, so the
profile just applies a second layer of weights across concepts -- it
doesn't need to know anything about the underlying raw metrics.

Rules:
  - Score ONLY numeric concept columns listed in weight_map.
  - Do NOT fold qualitative text fields (Medalist, letter grades,
    Risk Label, Management Style, Morningstar Risk Rating text) into
    the profile score. Those may exist on the frame for export/review only.
  - Score / rank columns are forced to plain float64 so Excel
    does not treat them as text.

To add a profile that only needs different thresholds or weights:
  1. Copy a YAML in input_files/ and set a new `profile:` key (e.g. "INC").
  2. Add that key to PROFILE_KEYS below.
  3. Add the YAML to config.PROFILE_INPUT_FILES so run_ci.py runs it.
A profile that needs different filter logic gets its own module in
profiles/ instead, imported once in main.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add parent directory to path so imports work when running scripts directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from functools import partial
from typing import Dict, List

import numpy as np
import pandas as pd

from config import DEFAULT_PROFILE_WEIGHTS
from scoring import (
    build_structure_flags,
    register_profile_filter,
    register_profile_prefilter,
    register_profile_scorer,
)


# Concept columns a profile may weight. Anything not in this map is ignored
# by the composite (including qualitative text columns).
CONCEPT_WEIGHT_KEYS: Dict[str, str] = {
    "Long_Term_Return_Performance_Score": "long_term_return_performance",
    "Short_Term_Return_Performance_Score": "short_term_return_performance",
    "Risk_Adjusted_Score": "risk_adjusted",
    "Volatility_Score": "volatility",
    "Resilience_Score": "resilience",
    "Tracking_Score": "tracking",
    "Liquidity_Size_Score": "liquidity_size",
    "Quality_Valuation_Score": "quality_valuation",
    "Costs_Score": "costs",
    "Tax_Income_Score": "tax_income",
}


def _as_float_series(s: pd.Series) -> pd.Series:
    """Coerce to float64; invalid values -> NaN. Never leave object/str."""
    return pd.to_numeric(s, errors="coerce").astype("float64")


def apply_prefilter(df: pd.DataFrame, thresholds: dict, key: str) -> pd.DataFrame:
    """
    The profile's hard rules on raw Morningstar columns, run right after the
    data is loaded so excluded funds are never downloaded from Yahoo and
    never affect the within-category scores of the funds that remain.
    Missing YAML keys fall back to the defaults below.
      - require_category, require_fund_size, require_3y_return (bool):
        funds without a category, fund size or full 3-year history are
        excluded, not scored on a shorter history
      - max_expense_ratio (percent)
      - exclude_leveraged_funds / exclude_interval_funds /
        exclude_tender_offer_funds (bool)
      - max_deferred_load, max_front_load (percent)
      - min_initial_investment (dollars): the HIGHEST minimum allowed;
        funds that require more are removed
      - max_redemption_fee (percent)
    Blank values pass (e.g. ETFs have no minimum initial investment).
    """
    start_count: int = len(df)
    eligible: pd.DataFrame = build_structure_flags(df)

    require_category = thresholds.get("require_category", True)
    max_expense_ratio = thresholds.get("max_expense_ratio", 0.75)
    require_fund_size = thresholds.get("require_fund_size", True)
    require_3y_return = thresholds.get("require_3y_return", True)

    if require_category and "Morningstar Category" in eligible.columns:
        before = len(eligible)
        eligible = eligible[eligible["Morningstar Category"].notna()]
        print(f"  Profile {key} filter - valid category: {before} -> {len(eligible)}")

    if max_expense_ratio is not None and "Net Expense Ratio" in eligible.columns:
        before = len(eligible)
        # Ensure comparison is numeric even if loader left strings
        expense = _as_float_series(eligible["Net Expense Ratio"])
        # Only filter out funds with non-null expense ratio that exceeds threshold
        # Allow funds with NaN expense ratio to pass through
        eligible = eligible[expense.isna() | (expense <= float(max_expense_ratio))]
        print(
            f"  Profile {key} filter - expense ratio <= {max_expense_ratio}% (or NaN): "
            f"{before} -> {len(eligible)}"
        )

    if require_fund_size and "Fund Size" in eligible.columns:
        before = len(eligible)
        eligible = eligible[eligible["Fund Size"].notna()]
        print(f"  Profile {key} filter - fund size present: {before} -> {len(eligible)}")

    if require_3y_return and "Total Return (3Y)" in eligible.columns:
        before = len(eligible)
        ret3 = _as_float_series(eligible["Total Return (3Y)"])
        eligible = eligible[ret3.notna()]
        print(f"  Profile {key} filter - has 3Y track record: {before} -> {len(eligible)}")

    # Structural exclusions -- leveraged/interval/tender-offer funds are
    # hard-excluded (when the YAML turns them on) regardless of how well
    # they score on the weighted concepts. Flag columns come from
    # scoring.build_structure_flags().
    exclude_leveraged_funds = thresholds.get("exclude_leveraged_funds", True)
    exclude_interval_funds = thresholds.get("exclude_interval_funds", True)
    exclude_tender_offer_funds = thresholds.get("exclude_tender_offer_funds", True)

    if exclude_leveraged_funds and "Flag_Leveraged_Fund" in eligible.columns:
        before = len(eligible)
        flag = eligible["Flag_Leveraged_Fund"].fillna(False).astype(bool)
        eligible = eligible[~flag]
        print(f"  Profile {key} filter - exclude leveraged funds: {before} -> {len(eligible)}")

    if exclude_interval_funds and "Flag_Interval_Fund" in eligible.columns:
        before = len(eligible)
        flag = eligible["Flag_Interval_Fund"].fillna(False).astype(bool)
        eligible = eligible[~flag]
        print(f"  Profile {key} filter - exclude interval funds: {before} -> {len(eligible)}")

    if exclude_tender_offer_funds and "Flag_Tender_Offer" in eligible.columns:
        before = len(eligible)
        flag = eligible["Flag_Tender_Offer"].fillna(False).astype(bool)
        eligible = eligible[~flag]
        print(f"  Profile {key} filter - exclude tender-offer funds: {before} -> {len(eligible)}")

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
            f"  Profile {key} filter - deferred load <= {max_deferred_load}% (or NaN): "
            f"{before} -> {len(eligible)}"
        )

    if max_front_load is not None and "Maximum Front Load" in eligible.columns:
        before = len(eligible)
        front_load = _as_float_series(eligible["Maximum Front Load"])
        # Only filter out funds with non-null front load that exceeds threshold
        # Allow funds with NaN front load to pass through
        eligible = eligible[front_load.isna() | (front_load <= float(max_front_load))]
        print(
            f"  Profile {key} filter - front load <= {max_front_load}% (or NaN): "
            f"{before} -> {len(eligible)}"
        )

    if min_initial_investment is not None and "Minimum Initial Investment" in eligible.columns:
        before = len(eligible)
        initial_inv = _as_float_series(eligible["Minimum Initial Investment"])
        # Only filter out funds with non-null initial investment that exceeds threshold
        # Allow funds with NaN initial investment to pass through
        eligible = eligible[initial_inv.isna() | (initial_inv <= float(min_initial_investment))]
        print(
            f"  Profile {key} filter - initial investment <= ${min_initial_investment:,} (or NaN): "
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
            f"  Profile {key} filter - redemption fee <= {max_redemption_fee}% (or NaN): "
            f"{before} -> {len(eligible)}"
        )

    print(f"Profile {key} eligibility filter (Morningstar rules): {start_count} -> {len(eligible)} rows remain.")
    return eligible.copy()


def apply_filters(df: pd.DataFrame, thresholds: dict, key: str) -> pd.DataFrame:
    """
    Profile rules that need data added during the run (yearly benchmark
    stats). Everything that only reads raw Morningstar columns runs earlier
    in apply_prefilter(), before the Yahoo downloads.
      - require_benchmark_outperformance / min_benchmark_beat_pct
    """
    start_count: int = len(df)
    eligible: pd.DataFrame = df.copy()

    # Historical benchmark performance filter
    require_benchmark_outperformance = thresholds.get("require_benchmark_outperformance", False)
    min_benchmark_beat_pct = thresholds.get("min_benchmark_beat_pct", 50.0)

    if require_benchmark_outperformance and "Yearly Beat %" in eligible.columns:
        before = len(eligible)
        better_pct = _as_float_series(eligible["Yearly Beat %"])
        # Require funds to beat benchmarks in at least X% of available years
        # Allow funds with NaN benchmark data to pass through
        eligible = eligible[better_pct.isna() | (better_pct >= float(min_benchmark_beat_pct))]
        print(
            f"  Profile {key} filter - benchmark outperformance >= {min_benchmark_beat_pct}% (or NaN): "
            f"{before} -> {len(eligible)}"
        )

    print(f"Profile {key} eligibility filter: {start_count} -> {len(eligible)} rows remain.")
    return eligible


def compute_score(df: pd.DataFrame, top_n: int, thresholds: dict, key: str) -> pd.DataFrame:
    """
    Weights come from thresholds["weights"] in the input YAML if present,
    otherwise fall back to config.DEFAULT_PROFILE_WEIGHTS. This blends the
    already-category-relative concept scores (each 0-100) into a single
    Profile_<key>_Score, then ranks it within each Morningstar Category
    and overall (1 = best).

    Expects df to already have gone through
    scoring.build_concept_scores(df) so the *_Score columns below exist.

    Stage A: qualitative columns are never read here.
    """
    if thresholds is None:
        thresholds = {}

    score_col = f"Profile_{key}_Score"
    rank_cat_col = f"Profile_{key}_Rank_In_Category"
    flag_cat_col = f"Profile_{key}_Selected_Flag"
    rank_all_col = f"Profile_{key}_Rank_Overall"
    flag_all_col = f"Profile_{key}_Selected_Overall_Flag"

    scored: pd.DataFrame = df.copy()
    weights = thresholds.get("weights", DEFAULT_PROFILE_WEIGHTS) or {}

    # Build weight_map: concept_col -> weight
    weight_map: Dict[str, float] = {}
    for concept_col, yaml_key in CONCEPT_WEIGHT_KEYS.items():
        weight_map[concept_col] = float(weights.get(yaml_key, 0.0))

    available_cols: List[str] = [c for c in weight_map if c in scored.columns]
    if not available_cols:
        raise ValueError(
            f"compute_score({key!r}): none of the expected concept-score "
            "columns are present. Did you run build_concept_scores() "
            "before calling this function?\n"
            f"Expected any of: {list(CONCEPT_WEIGHT_KEYS)}\n"
            f"Present columns sample: {list(scored.columns)[:40]}"
        )

    missing_cols = [c for c in weight_map if c not in scored.columns]
    if missing_cols:
        print(
            f"  Note: Profile {key} scoring proceeding without {missing_cols} "
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
            f"  Warning: all Profile {key} concept weights are 0; "
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
    scored[score_col] = pd.Series(row_scores, index=scored.index, dtype="float64")
    scored[score_col] = _as_float_series(scored[score_col]).round(6)

    # ---- ranks as float64 (Excel-friendly; still 1,2,3,...) ----
    if "Morningstar Category" in scored.columns:
        scored[rank_cat_col] = (
            scored.groupby("Morningstar Category", dropna=False)[score_col]
            .rank(method="min", ascending=False)
        )
    else:
        scored[rank_cat_col] = scored[score_col].rank(
            method="min", ascending=False
        )

    scored[rank_cat_col] = _as_float_series(
        scored[rank_cat_col]
    )

    scored[flag_cat_col] = (
        scored[rank_cat_col].le(float(top_n)).fillna(False).astype(bool)
    )

    scored[rank_all_col] = scored[score_col].rank(
        method="min", ascending=False
    )
    scored[rank_all_col] = _as_float_series(scored[rank_all_col])

    scored[flag_all_col] = (
        scored[rank_all_col].le(float(top_n)).fillna(False).astype(bool)
    )

    # Console proof (helps catch str regression early)
    print(
        f"  Profile {key} score dtypes: "
        f"Score={scored[score_col].dtype}, "
        f"RankInCat={scored[rank_cat_col].dtype}, "
        f"RankOverall={scored[rank_all_col].dtype}"
    )
    if str(scored[score_col].dtype) == "object":
        raise TypeError(f"{score_col} is object/str after scoring -- aborting.")

    return scored


# Profile keys that use this module's logic. Each YAML's `profile:` value
# must be one of these.
PROFILE_KEYS = ("LT", "ST")

for _key in PROFILE_KEYS:
    register_profile_prefilter(_key)(partial(apply_prefilter, key=_key))
    register_profile_filter(_key)(partial(apply_filters, key=_key))
    register_profile_scorer(_key)(partial(compute_score, key=_key))
