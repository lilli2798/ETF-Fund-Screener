"""
Weighted profiles: composite scoring/ranking logic shared by every profile
whose behaviour is set entirely by its YAML file. It scores every fund and
never removes one (rules for all profiles are config.PURCHASE_RULES).

Every input_files/profile_*.yaml uses this module, e.g.
  - "LT"  input_files/profile_long_term.yaml   long-term, low-risk buy list
  - "ST"  input_files/profile_short_term.yaml  short-term momentum buy list

register(key) gives a profile key its own scorer in
scoring.PROFILE_SCORERS, plus its
own output columns (Profile_LT_Score, Profile_ST_Score, ...). main.py
registers each YAML's `profile:` key when it runs it. Run together, the
profiles share one report (results_profile_LT_ST_...).

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

To add a profile that only needs different thresholds or weights, copy a
profile_*.yaml in input_files/ and set a new `profile:` key (e.g. "INC").
Nothing else to change. A profile that needs different filter logic gets
its own module in profiles/ instead, which registers its key itself and is
imported once in main.py.
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

from scoring import (
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


def compute_score(df: pd.DataFrame, top_n: int, thresholds: dict, key: str) -> pd.DataFrame:
    """
    Weights come from thresholds["weights"] in the profile YAML. This blends the
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
    weights = thresholds["weights"]

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

    # top_n_overall (YAML, top level) sets the overall cutoff separately;
    # if it's not set, the per-category top_n is used for both.
    top_n_overall = thresholds.get("top_n_overall") or top_n
    scored[flag_all_col] = (
        scored[rank_all_col].le(float(top_n_overall)).fillna(False).astype(bool)
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


def register(key: str) -> None:
    """Give profile `key` (a YAML's `profile:` value) this module's scorer."""
    register_profile_scorer(key)(partial(compute_score, key=key))
