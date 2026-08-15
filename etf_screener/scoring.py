"""
Shared scoring logic (concept scores used by every profile) plus a
profile registry so new profiles can be added without editing this file
or main.py.

Design notes (locked in from project discussion):
  - All continuous metrics are normalized WITHIN Morningstar Category
    (not globally), since volatility/return/tracking error behavior
    differs a lot by category and a global min-max would unfairly
    penalize inherently-higher-risk categories.
  - Concept scoring is split into one function per concept group so
    each stays independently testable and reusable across profiles.
  - Categorical/flag-style concepts (Sector/Exposure, Manager &
    Stewardship, Structure & Flags) are intentionally NOT scored 0-100
    here yet -- they are left as separate raw/flag columns until the
    filter-vs-score decision is finalized.
"""

from typing import Callable, Dict, List, Optional
import pandas as pd

from config import GRADE_TO_NUMERIC, MEDALIST_TO_NUMERIC, STAR_RATING_TO_NUMERIC


# --- Profile registry -------------------------------------------------
# Each profile module (e.g. profiles/profile_a.py) registers its own
# eligibility-filter function and scoring function here via the
# decorators below. main.py never needs to know how many profiles exist
# or what their names are -- it just looks them up by profile_name.

PROFILE_FILTERS: Dict[str, Callable[[pd.DataFrame, dict], pd.DataFrame]] = {}
PROFILE_SCORERS: Dict[str, Callable[[pd.DataFrame, int, dict], pd.DataFrame]] = {}

DEFAULT_CATEGORY_COL: str = "Morningstar Category"


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


def _medalist_to_numeric(value) -> Optional[float]:
    """Map Medalist Rating (e.g. 'Gold') to a numeric score via MEDALIST_TO_NUMERIC."""
    if pd.isna(value):
        return None
    key = str(value).strip().upper()
    return MEDALIST_TO_NUMERIC.get(key)


def _star_rating_to_numeric(value) -> Optional[float]:
    """Map Morningstar Rating for Funds (star rating) to a numeric score via STAR_RATING_TO_NUMERIC."""
    if pd.isna(value):
        return None
    key = str(value).strip()
    return STAR_RATING_TO_NUMERIC.get(key)



def normalize_within_category(
    df: pd.DataFrame,
    col: str,
    category_col: str = DEFAULT_CATEGORY_COL,
    invert: bool = False,
) -> pd.Series:
    """
    Normalize a numeric column to a 0-100 scale using percentile rank
    WITHIN each Morningstar Category (falls back to a single global
    group if `category_col` is missing from df).

    If `invert` is True, lower raw values map to a HIGHER score
    (useful for "lower is better" metrics like expense ratio, risk
    score, standard deviation, tracking error, or max drawdown).

    Missing/NaN inputs stay NaN in the output so a missing metric does
    not unfairly tank -- or inflate -- a fund's composite score. A
    category with only 1 non-null value gets a neutral 50.0, since
    there's no spread to rank against.
    """
    if col not in df.columns:
        return pd.Series([float("nan")] * len(df), index=df.index)

    numeric: pd.Series = pd.to_numeric(df[col], errors="coerce")

    if category_col in df.columns:
        groups = numeric.groupby(df[category_col])
    else:
        groups = numeric.groupby(lambda _: "__all__")

    def _rank_group(s: pd.Series) -> pd.Series:
        valid = s.dropna()
        if len(valid) <= 1:
            return s.apply(lambda v: 50.0 if pd.notna(v) else float("nan"))
        pct = s.rank(pct=True, na_option="keep") * 100.0
        return (100.0 - pct) if invert else pct

    result = groups.apply(_rank_group)
    # groupby(...).apply on a Series can return a MultiIndex; align back
    # to the original row order/index.
    if isinstance(result.index, pd.MultiIndex):
        result = result.droplevel(0)
    return result.reindex(df.index).round(2)


def _weighted_average(df: pd.DataFrame, weight_map: Dict[str, float]) -> pd.Series:
    """
    Row-wise weighted average across the columns in `weight_map`,
    re-normalizing weights per-row to only the columns that are
    non-NaN for that row (so one missing metric doesn't zero out the
    whole score).
    """
    available_cols = [c for c in weight_map if c in df.columns]
    if not available_cols:
        return pd.Series([float("nan")] * len(df), index=df.index)

    def _row_score(row: pd.Series) -> float:
        total_weight = 0.0
        weighted_sum = 0.0
        for col in available_cols:
            val = row[col]
            if pd.notna(val):
                w = weight_map[col]
                weighted_sum += val * w
                total_weight += w
        if total_weight == 0.0:
            return float("nan")
        return weighted_sum / total_weight

    return df[available_cols].apply(_row_score, axis=1).round(2)



# Every column-level weight key each concept function actually consumes.
# Used by _require_weights() to enforce STRICT validation: a concept's
# weight dict must supply every one of these keys explicitly (no partial
# overrides silently filled with hardcoded defaults). To intentionally
# drop/remove one metric from a concept, set its weight to 0.0 in
# config.DEFAULT_CONCEPT_WEIGHTS / thresholds.concept_weights -- the key
# must still be present, just zeroed out, so it's clear that was a
# deliberate choice and not a missing/forgotten setting.
REQUIRED_CONCEPT_KEYS: Dict[str, List[str]] = {
    "performance": ["return_3y", "return_5y", "return_1y", "rank_3y"],
    "long_term_return_performance": [
        "return_1y", "return_2y", "return_3y", "return_4y", "return_5y",
        "return_6y", "return_7y", "return_8y", "return_9y", "return_10y",
        "return_15y", "return_20y"
    ],
    "short_term_return_performance": [
        "return_1w", "return_1m", "return_2m", "return_qtd",
        "return_3m", "return_6m", "return_9m", "return_ytd"
    ],
    "risk_adjusted": [
        "sharpe_3y", "sharpe_1y", "upside", "downside",
        "yahoo_sharpe_3y", "yahoo_sharpe_1y", "yahoo_zscore_3y", "yahoo_zscore_1y",
    ],
    "volatility": ["stdev_3y", "drawdown_3y", "drawdown_5y"],
    "tracking": ["tracking_error_3y", "tracking_error_1y"],
    "liquidity_size": ["fund_size", "trading_volume"],
    "quality_valuation": ["growth_grade", "financial_health", "price_fair_value", "medalist", "star_rating" ],
    "costs": ["adjusted_expense_ratio"],
    "tax_income": ["tax_cost_ratio_1y", "tax_cost_ratio_2y", "sec_yield"],
}


def _require_weights(weights: Optional[Dict[str, float]], concept_name: str) -> Dict[str, float]:
    """Strictly validate a concept's weight map: it must be non-empty AND
    contain every key listed in REQUIRED_CONCEPT_KEYS[concept_name] --
    no silent fallback to a hardcoded default for the whole dict OR for
    any individual missing key. Raises a specific ValueError naming the
    concept and any missing key(s), so a forgotten/misspelled config
    entry fails loudly and immediately instead of quietly using a
    default weight nobody actually chose.

    To intentionally remove a metric from a concept's score, set its
    weight to 0.0 rather than omitting the key -- this keeps the choice
    explicit and auditable in the used-weights report generated after
    each run (see export.write_used_weights_report()).
    """
    if not weights:
        raise ValueError(
            f"Missing weights for concept '{concept_name}'. Add a "
            f"'{concept_name}' entry to config.DEFAULT_CONCEPT_WEIGHTS "
            f"(or thresholds.concept_weights.{concept_name} in your profile "
            f"YAML) -- no hardcoded fallback is used, so this must be set explicitly."
        )

    required_keys = REQUIRED_CONCEPT_KEYS.get(concept_name, [])
    missing_keys = [k for k in required_keys if k not in weights]
    if missing_keys:
        raise ValueError(
            f"Concept '{concept_name}' is missing required weight key(s): "
            f"{missing_keys}. Every key must be present in "
            f"config.DEFAULT_CONCEPT_WEIGHTS['{concept_name}'] (or your profile "
            f"YAML's thresholds.concept_weights.{concept_name}) -- set a key to "
            f"0.0 to intentionally remove that metric, don't just omit it."
        )
    return weights


# --- 1. Performance & return ranks -------------------------------------

def calculate_return_rankings(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add ranking columns for all return periods.
    Ranks funds within each return period (higher return = better rank).
    
    Args:
        df: DataFrame with return columns
    
    Returns:
        DataFrame with added ranking columns
    """
    return_periods = [
        "Total Return (1W)", "Total Return (1M)", "Total Return (2M)", "Total Return (QTD)",
        "Total Return (3M)", "Total Return (6M)", "Total Return (9M)", "Total Return (YTD)",
        "Total Return (1Y)", "Total Return (2Y)", "Total Return (3Y)",
        "Total Return (4Y)", "Total Return (5Y)", "Total Return (6Y)",
        "Total Return (7Y)", "Total Return (8Y)", "Total Return (9Y)",
        "Total Return (10Y)", "Total Return (15Y)", "Total Return (20Y)"
    ]
    
    result = df.copy()
    
    for period in return_periods:
        if period in df.columns:
            # Rank returns (higher return = better rank, so rank in descending order)
            rank_col = period.replace("Total Return", "Return Rank")
            result[rank_col] = df[period].rank(ascending=False, method='min')
    
    return result


def calculate_long_term_return_performance_score(
    df: pd.DataFrame,
    category_col: str = DEFAULT_CATEGORY_COL,
    weights: Optional[Dict[str, float]] = None,
) -> pd.Series:
    """
    Long-term return score that aggregates performance across all available
    return periods (1Y through 20Y). Each period is normalized within category
    and then averaged. This rewards consistent long-term performance across
    multiple time horizons rather than just recent performance.
    """
    weights = _require_weights(weights, "long_term_return_performance")

    # All available return periods from 1Y to 20Y
    return_periods = [
        "Total Return (1Y)", "Total Return (2Y)", "Total Return (3Y)",
        "Total Return (4Y)", "Total Return (5Y)", "Total Return (6Y)",
        "Total Return (7Y)", "Total Return (8Y)", "Total Return (9Y)",
        "Total Return (10Y)", "Total Return (15Y)", "Total Return (20Y)"
    ]

    out = pd.DataFrame(index=df.index)

    # Normalize each return period within category
    for period in return_periods:
        if period in df.columns:
            norm_col = period.replace("Total Return", "Norm_Return")
            out[norm_col] = normalize_within_category(df, period, category_col)

    # If weights are provided, use them; otherwise equal weight all available periods
    if weights:
        weight_map = {}
        for period in return_periods:
            norm_col = period.replace("Total Return", "Norm_Return")
            if norm_col in out.columns:
                # Map period to weight key (e.g., "return_1y", "return_5y", etc.)
                weight_key = "return_" + period.replace("Total Return (", "").replace(")", "").lower()
                weight_map[norm_col] = weights.get(weight_key, 0.0)
        return _weighted_average(out, weight_map)
    else:
        # Equal weight all available normalized returns
        available_cols = [col for col in out.columns if col.startswith("Norm_Return")]
        if available_cols:
            return out[available_cols].mean(axis=1)
        return pd.Series([float("nan")] * len(df), index=df.index)


def calculate_short_term_return_performance_score(
    df: pd.DataFrame,
    category_col: str = DEFAULT_CATEGORY_COL,
    weights: Optional[Dict[str, float]] = None,
) -> pd.Series:
    """
    Short-term return score that aggregates performance across short-term
    return periods (1W through YTD). Each period is normalized within category
    and then averaged. This rewards recent momentum and short-term performance.
    """
    weights = _require_weights(weights, "short_term_return_performance")

    # Short-term return periods
    return_periods = [
        "Total Return (1W)", "Total Return (1M)", "Total Return (2M)",
        "Total Return (QTD)", "Total Return (3M)", "Total Return (6M)",
        "Total Return (9M)", "Total Return (YTD)"
    ]

    out = pd.DataFrame(index=df.index)

    # Normalize each return period within category
    for period in return_periods:
        if period in df.columns:
            norm_col = period.replace("Total Return", "Norm_Return")
            out[norm_col] = normalize_within_category(df, period, category_col)

    # If weights are provided, use them; otherwise equal weight all available periods
    if weights:
        weight_map = {}
        for period in return_periods:
            norm_col = period.replace("Total Return", "Norm_Return")
            if norm_col in out.columns:
                # Map period to weight key (e.g., "return_1w", "return_1m", etc.)
                weight_key = "return_" + period.replace("Total Return (", "").replace(")", "").lower()
                weight_map[norm_col] = weights.get(weight_key, 0.0)
        return _weighted_average(out, weight_map)
    else:
        # Equal weight all available normalized returns
        available_cols = [col for col in out.columns if col.startswith("Norm_Return")]
        if available_cols:
            return out[available_cols].mean(axis=1)
        return pd.Series([float("nan")] * len(df), index=df.index)


# --- 2. Risk-adjusted performance (Sharpe, upside/downside capture) ----

def calculate_risk_adjusted_score(
    df: pd.DataFrame,
    category_col: str = DEFAULT_CATEGORY_COL,
    weights: Optional[Dict[str, float]] = None,
) -> pd.Series:
    """
    Risk-adjusted score blending Morningstar Sharpe/upside/downside with
    Yahoo-derived Sharpe and sector-relative Z-scores when available.
    Downside capture is inverted (lower downside capture = better).
    Missing Yahoo data simply drops out of the row-wise weighted average
    instead of penalizing the fund.
    """
    weights = _require_weights(weights, "risk_adjusted")

    out = pd.DataFrame(index=df.index)
    out["Norm_Sharpe_3Y"] = normalize_within_category(df, "Sharpe Ratio (3Y Monthly)", category_col)
    out["Norm_Sharpe_1Y"] = normalize_within_category(df, "Sharpe Ratio (1Y Monthly)", category_col)
    out["Norm_Upside_Capture"] = normalize_within_category(df, "Upside Capture Ratio (3Y)", category_col)
    out["Norm_Downside_Capture"] = normalize_within_category(
        df, "Downside Capture Ratio (3Y)", category_col, invert=True
    )
    out["Norm_Yahoo_Sharpe_3Y"] = normalize_within_category(df, "Sharpe_3Y", category_col)
    out["Norm_Yahoo_Sharpe_1Y"] = normalize_within_category(df, "Sharpe_1Y", category_col)
    out["Norm_Yahoo_ZScore_3Y"] = normalize_within_category(df, "Z_Score_3Y", category_col)
    out["Norm_Yahoo_ZScore_1Y"] = normalize_within_category(df, "Z_Score_1Y", category_col)

    weight_map = {
        "Norm_Sharpe_3Y": weights["sharpe_3y"],
        "Norm_Sharpe_1Y": weights["sharpe_1y"],
        "Norm_Upside_Capture": weights["upside"],
        "Norm_Downside_Capture": weights["downside"],
        "Norm_Yahoo_Sharpe_3Y": weights["yahoo_sharpe_3y"],
        "Norm_Yahoo_Sharpe_1Y": weights["yahoo_sharpe_1y"],
        "Norm_Yahoo_ZScore_3Y": weights["yahoo_zscore_3y"],
        "Norm_Yahoo_ZScore_1Y": weights["yahoo_zscore_1y"],
    }
    return _weighted_average(out, weight_map)


# --- 3. Volatility & downside risk --------------------------------------

def calculate_volatility_score(
    df: pd.DataFrame,
    category_col: str = DEFAULT_CATEGORY_COL,
    weights: Optional[Dict[str, float]] = None,
) -> pd.Series:
    """
    Standard Deviation (3Y) and Max Drawdown (3Y/5Y), all inverted
    (lower volatility/drawdown = higher score) and normalized within
    category.
    """
    weights = _require_weights(weights, "volatility")

    out = pd.DataFrame(index=df.index)
    out["Norm_Stdev_3Y"] = normalize_within_category(
        df, "Standard Deviation (3Y Monthly)", category_col, invert=True
    )
    out["Norm_Drawdown_3Y"] = normalize_within_category(
        df, "Maximum Drawdown (3Y)", category_col, invert=True
    )
    out["Norm_Drawdown_5Y"] = normalize_within_category(
        df, "Maximum Drawdown (5Y)", category_col, invert=True
    )

    weight_map = {
        "Norm_Stdev_3Y": weights["stdev_3y"],
        "Norm_Drawdown_3Y": weights["drawdown_3y"],
        "Norm_Drawdown_5Y": weights["drawdown_5y"],
    }
    return _weighted_average(out, weight_map)


# --- 4. Tracking quality -------------------------------------------------

def calculate_tracking_score(
    df: pd.DataFrame,
    category_col: str = DEFAULT_CATEGORY_COL,
    weights: Optional[Dict[str, float]] = None,
) -> pd.Series:
    """
    Tracking Error (1Y/3Y), inverted and normalized within category.
    Per project decision: only 1Y and 3Y are used, not 5Y/10Y+.
    """
    weights = _require_weights(weights, "tracking")

    out = pd.DataFrame(index=df.index)
    out["Norm_Tracking_Error_3Y"] = normalize_within_category(
        df, "Tracking Error (3Y Monthly)", category_col, invert=True
    )
    out["Norm_Tracking_Error_1Y"] = normalize_within_category(
        df, "Tracking Error (1Y Monthly)", category_col, invert=True
    )

    weight_map = {
        "Norm_Tracking_Error_3Y": weights["tracking_error_3y"],
        "Norm_Tracking_Error_1Y": weights["tracking_error_1y"],
    }
    return _weighted_average(out, weight_map)


# --- 5. Liquidity & size --------------------------------------------------

def score_piecewise(
    series: pd.Series,
    floor: float,
    target: float,
    ceiling: float,
    invert: bool = False,
) -> pd.Series:
    """
    Non-normalized (NOT category-relative) piecewise scorer, used for
    metrics whose meaning is stable across the whole ETF universe
    (e.g. expense ratio, fund size) rather than dependent on
    category/sub-industry peers.

    Maps raw values to a fixed 0-100 scale using three business-defined
    cutoffs instead of percentile rank within category:
      - At/beyond `floor`  -> 0   (bad end of the range)
      - At `target`        -> 80 ("good enough" -- most of the credit)
      - At/beyond `ceiling` -> 100 (no extra benefit past this point)
    Values between cutoffs are linearly interpolated. If `invert` is
    False, higher raw values are better (e.g. Fund Size, Trading
    Volume) so floor < target < ceiling. If `invert` is True, lower
    raw values are better (e.g. Net Expense Ratio, Management Fee) so
    floor > target > ceiling.

    Missing/NaN inputs stay NaN in the output (same missing-data
    convention as `normalize_within_category`).
    """
    numeric = pd.to_numeric(series, errors="coerce")

    def _score_one(v: float) -> float:
        if pd.isna(v):
            return float("nan")
        if not invert:
            if v <= floor:
                return 0.0
            if v >= ceiling:
                return 100.0
            if v <= target:
                return 80.0 * (v - floor) / (target - floor)
            return 80.0 + 20.0 * (v - target) / (ceiling - target)
        else:
            if v >= floor:
                return 0.0
            if v <= ceiling:
                return 100.0
            if v >= target:
                return 80.0 * (floor - v) / (floor - target)
            return 80.0 + 20.0 * (target - v) / (target - ceiling)

    return numeric.apply(_score_one).round(2)


def calculate_liquidity_size_score(
    df: pd.DataFrame,
    category_col: str = DEFAULT_CATEGORY_COL,
    weights: Optional[Dict[str, float]] = None,
    thresholds: Optional[Dict[str, Dict[str, float]]] = None,
) -> pd.Series:
    """
    Fund Size (AUM) and Trading Volume, scored with FIXED thresholds
    across the whole universe (NOT normalized within category).

    Rationale: fund size and trading volume are driven mainly by fund
    age, popularity, and provider scale -- not by sector/sub-industry
    composition -- so a global "liquid enough" bar is more accurate
    than comparing a fund only to peers that happen to share its
    Morningstar Category. See docs/column_glossary.md, "Category
    Dependence of the 8 Scored Concepts", for the full rationale.

    Default thresholds (override via `thresholds` if needed):
      - Fund Size ($):        floor=$10M, target=$500M, ceiling=$5B
      - Trading Volume (shares/day): floor=5,000, target=100,000, ceiling=1,000,000
    """
    weights = _require_weights(weights, "liquidity_size")
    thresholds = thresholds or {
        "fund_size": {"floor": 10_000_000, "target": 500_000_000, "ceiling": 5_000_000_000},
        "trading_volume": {"floor": 5_000, "target": 100_000, "ceiling": 1_000_000},
    }

    out = pd.DataFrame(index=df.index)
    if "Fund Size" in df.columns:
        t = thresholds["fund_size"]
        out["Score_Fund_Size"] = score_piecewise(
            df["Fund Size"], t["floor"], t["target"], t["ceiling"], invert=False
        )
    if "Trading Volume" in df.columns:
        t = thresholds["trading_volume"]
        out["Score_Trading_Volume"] = score_piecewise(
            df["Trading Volume"], t["floor"], t["target"], t["ceiling"], invert=False
        )

    weight_map = {
        "Score_Fund_Size": weights["fund_size"],
        "Score_Trading_Volume": weights["trading_volume"],
    }
    return _weighted_average(out, weight_map)


def calculate_liquidity_size_score_category_normalized(
    df: pd.DataFrame,
    category_col: str = DEFAULT_CATEGORY_COL,
    weights: Optional[Dict[str, float]] = None,
) -> pd.Series:
    """
    LEGACY VERSION (kept for comparison/rollback only -- not called by
    any profile). Original category-relative percentile implementation
    of Liquidity & Size, prior to the non-normalized rewrite above.
    """
    weights = _require_weights(weights, "liquidity_size")

    out = pd.DataFrame(index=df.index)
    out["Norm_Fund_Size"] = normalize_within_category(df, "Fund Size", category_col)
    out["Norm_Trading_Volume"] = normalize_within_category(df, "Trading Volume", category_col)

    weight_map = {
        "Norm_Fund_Size": weights["fund_size"],
        "Norm_Trading_Volume": weights["trading_volume"],
    }
    return _weighted_average(out, weight_map)


# --- 6. Quality, valuation & portfolio characteristics -------------------

def calculate_quality_valuation_score(
    df: pd.DataFrame,
    category_col: str = DEFAULT_CATEGORY_COL,
    weights: Optional[Dict[str, float]] = None,
) -> pd.Series:
    """
    Portfolio Growth/Financial Health letter grades (converted to
    numeric), Medalist Rating, plus Price/Fair Value, normalized
    within category.

    Price/Fair Value is inverted -- priced above fair value (ratio > 1)
    is generally less attractive than trading at/below it.
    Medalist is higher-is-better (Gold > Silver > Bronze > Neutral).
    """
    weights = _require_weights(weights, "quality_valuation")

    out = pd.DataFrame(index=df.index)

    if "Portfolio Growth Grade" in df.columns:
        out["Growth_Grade_Numeric"] = df["Portfolio Growth Grade"].apply(_grade_to_numeric)
        out["Norm_Growth_Grade"] = normalize_within_category(
            out, "Growth_Grade_Numeric", category_col
        )

    if "Portfolio Financial Health Grade" in df.columns:
        out["Financial_Health_Grade_Numeric"] = df["Portfolio Financial Health Grade"].apply(
            _grade_to_numeric
        )
        out["Norm_Financial_Health"] = normalize_within_category(
            out, "Financial_Health_Grade_Numeric", category_col
        )

    # NEW: Medalist Rating (Overall) -> numeric -> category percentile
    medalist_col = None
    for candidate in ("Medalist Rating (Overall)", "Medalist Rating", "Morningstar Medalist Rating"):
        if candidate in df.columns:
            medalist_col = candidate
            break

    if medalist_col is not None:
        out["Medalist_Numeric"] = df[medalist_col].apply(_medalist_to_numeric)
        out["Norm_Medalist"] = normalize_within_category(
            out, "Medalist_Numeric", category_col
        )
    elif "Medalist_Numeric" in df.columns:
        # already built by build_qualitative_review_columns
        out["Medalist_Numeric"] = pd.to_numeric(df["Medalist_Numeric"], errors="coerce")
        out["Norm_Medalist"] = normalize_within_category(
            out, "Medalist_Numeric", category_col
        )

    # NEW: Morningstar Rating for Funds (star rating) -> numeric -> category percentile
    star_rating_col = None
    for candidate in ("Morningstar Rating for Funds (Overall)", "Morningstar Rating for Funds", "Morningstar Rating"):
        if candidate in df.columns:
            star_rating_col = candidate
            break

    if star_rating_col is not None:
        out["Star_Rating_Numeric"] = df[star_rating_col].apply(_star_rating_to_numeric)
        out["Norm_Star_Rating"] = normalize_within_category(
            out, "Star_Rating_Numeric", category_col
        )
    elif "Star_Rating_Numeric" in df.columns:
        # already built by build_qualitative_review_columns
        out["Star_Rating_Numeric"] = pd.to_numeric(df["Star_Rating_Numeric"], errors="coerce")
        out["Norm_Star_Rating"] = normalize_within_category(
            out, "Star_Rating_Numeric", category_col
        )

    if "Price/Fair Value" in df.columns:
        out["Norm_Price_Fair_Value"] = normalize_within_category(
            df, "Price/Fair Value", category_col, invert=True
        )

    # Portfolio Economic Moat Coverage (Wide) - percentage of portfolio with wide moat
    if "Portfolio Economic Moat Coverage (Wide)" in df.columns:
        out["Norm_Economic_Moat_Wide"] = normalize_within_category(
            df, "Portfolio Economic Moat Coverage (Wide)", category_col
        )

    weight_map = {
        "Norm_Growth_Grade": weights["growth_grade"],
        "Norm_Financial_Health": weights["financial_health"],
        "Norm_Price_Fair_Value": weights["price_fair_value"],
        "Norm_Medalist": weights["medalist"],  # NEW
        "Norm_Star_Rating": weights["star_rating"],  # NEW
        "Norm_Economic_Moat_Wide": weights["economic_moat_wide"],  # NEW
    }
    return _weighted_average(out, weight_map)


# --- 7. Costs & fees -------------------------------------------------------

def calculate_costs_score(
    df: pd.DataFrame,
    category_col: str = DEFAULT_CATEGORY_COL,
    weights: Optional[Dict[str, float]] = None,
) -> pd.Series:
    """
    Adjusted Expense Ratio, inverted and normalized within category
    (lower cost = higher score).
    """
    weights = _require_weights(weights, "costs")

    out = pd.DataFrame(index=df.index)
    out["Norm_Adjusted_Expense_Ratio"] = normalize_within_category(
        df, "Adjusted Expense Ratio", category_col, invert=True
    )

    weight_map = {
        "Norm_Adjusted_Expense_Ratio": weights["adjusted_expense_ratio"],
    }
    return _weighted_average(out, weight_map)


# --- 8. Tax & income --------------------------------------------------------

def calculate_tax_income_score(
    df: pd.DataFrame,
    category_col: str = DEFAULT_CATEGORY_COL,
    weights: Optional[Dict[str, float]] = None,
) -> pd.Series:
    """
    Tax Cost Ratio (1Y and 2Y, inverted - lower is better for tax efficiency)
    and SEC 30-Day Yield (higher is better), normalized within category.
    """
    weights = _require_weights(weights, "tax_income")

    out = pd.DataFrame(index=df.index)
    out["Norm_Tax_Cost_Ratio_1Y"] = normalize_within_category(
        df, "Tax Cost Ratio (1Y)", category_col, invert=True
    )
    out["Norm_Tax_Cost_Ratio_2Y"] = normalize_within_category(
        df, "Tax Cost Ratio (2Y)", category_col, invert=True
    )
    out["Norm_SEC_Yield"] = normalize_within_category(df, "SEC 30-Day Yield", category_col)

    weight_map = {
        "Norm_Tax_Cost_Ratio_1Y": weights["tax_cost_ratio_1y"],
        "Norm_Tax_Cost_Ratio_2Y": weights["tax_cost_ratio_2y"],
        "Norm_SEC_Yield": weights["sec_yield"],
    }
    return _weighted_average(out, weight_map)


# --- 9-11. Flags / not-yet-scored concepts --------------------------------
# Per project decision: Sector/Exposure, Manager & Stewardship, and
# Structure & Flags are kept as raw/flag columns for now, NOT folded
# into a 0-100 score, until the filter-vs-score approach is decided.

def build_sector_exposure_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Placeholder: attach raw sector/exposure fields as-is, unscored."""
    out = df.copy()
    # e.g. concentration checks could go here later as boolean flags,
    # such as Flag_High_Sector_Concentration.
    return out


def build_manager_stewardship_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Placeholder: attach raw manager/stewardship fields as-is, unscored."""
    out = df.copy()
    # Manager tenure and new manager flags removed - user will manually check for manager changes
    return out


def build_structure_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Placeholder: attach raw structure/flag fields as-is, unscored."""
    out = df.copy()
    for flag_col in ("Leveraged Fund", "Interval Fund", "Fund of Funds", "Tender Offer"):
        if flag_col in out.columns:
            out[f"Flag_{flag_col.replace(' ', '_')}"] = out[flag_col].astype(str).str.upper().eq("YES")
    return out


# --- Orchestrator -----------------------------------------------------

def build_concept_scores(
    df: pd.DataFrame,
    category_col: str = DEFAULT_CATEGORY_COL,
    concept_weights: Optional[Dict[str, Dict[str, float]]] = None,
) -> pd.DataFrame:
    """
    Build every concept score/feature used across all profiles, before
    any profile-specific filtering or weighting happens. Adding a
    concept score here once makes it available to every current and
    future profile.

    `concept_weights` lets you override the COLUMN-level weights inside
    each concept function (e.g. how much Total Return 3Y vs 5Y counts
    within Performance_Score), separate from the profile-level weights
    in PROFILE_A_WEIGHTS (which control how much each concept counts
    relative to the other concepts). Pass a dict keyed by concept name,
    each mapping to that concept function's own weight keys, e.g.:

        concept_weights = {
            "performance": {"return_3y": 0.40, "return_5y": 0.35, ...},
            "volatility":  {"stdev_3y": 0.45, "drawdown_3y": 0.30, ...},
        }

    Any concept omitted from `concept_weights` falls back to that
    function's own built-in defaults. This is typically populated from
    the profile input YAML's `thresholds.concept_weights` block.

    Adds:
      - Long_Term_Return_Performance_Score (aggregates 1Y-20Y returns)
      - Short_Term_Return_Performance_Score (aggregates 1W-YTD returns)
      - Risk_Adjusted_Score
      - Volatility_Score
      - Tracking_Score
      - Liquidity_Size_Score
      - Quality_Valuation_Score
      - Costs_Score
      - Tax_Income_Score
      - Sector/Manager/Structure flag columns (unscored, see above)

    Missing source columns are skipped gracefully (handled inside each
    calculate_*_score function) so this works even if a data source
    doesn't have every field.
    """
    out: pd.DataFrame = df.copy()
    cw = concept_weights or {}

    out["Long_Term_Return_Performance_Score"] = calculate_long_term_return_performance_score(
        out, category_col, weights=cw.get("long_term_return_performance")
    )
    out["Short_Term_Return_Performance_Score"] = calculate_short_term_return_performance_score(
        out, category_col, weights=cw.get("short_term_return_performance")
    )
    out["Risk_Adjusted_Score"] = calculate_risk_adjusted_score(
        out, category_col, weights=cw.get("risk_adjusted")
    )
    out["Volatility_Score"] = calculate_volatility_score(
        out, category_col, weights=cw.get("volatility")
    )
    out["Tracking_Score"] = calculate_tracking_score(
        out, category_col, weights=cw.get("tracking")
    )
    out["Liquidity_Size_Score"] = calculate_liquidity_size_score(
        out, category_col, weights=cw.get("liquidity_size")
    )
    out["Quality_Valuation_Score"] = calculate_quality_valuation_score(
        out, category_col, weights=cw.get("quality_valuation")
    )
    out["Costs_Score"] = calculate_costs_score(
        out, category_col, weights=cw.get("costs")
    )
    out["Tax_Income_Score"] = calculate_tax_income_score(
        out, category_col, weights=cw.get("tax_income")
    )

    out = build_sector_exposure_flags(out)
    out = build_manager_stewardship_flags(out)
    out = build_structure_flags(out)

    return out
