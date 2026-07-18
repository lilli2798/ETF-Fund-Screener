# Profile A — Design Doc

*Status: living document, written retroactively to capture the current
state of Profile A after an iterative refactor. Reflects what is
actually implemented in code today, not a spec written up front.*

---

## 1. Purpose

Profile A represents a **long-term, low-risk, steady-return** ETF
selection philosophy. It ranks eligible ETFs within each Morningstar
Category and flags the top N per category (plus a separate overall
top N), based on a weighted composite of 8 scored concept groups.

---

## 2. Pipeline Overview

```
load structural data ──┐
                        ├─> merge on Ticker ─> ETF-only filter
load performance data ──┘
                                │
                                v
                    build_concept_scores(df, concept_weights)
                    (scoring.py — computes 8 concept scores
                     + 3 unscored structural/flag columns)
                                │
                                v
                    apply_profile_A_filters(df, thresholds)
                    (profiles/profile_a.py — hard eligibility gates)
                                │
                                v
                    compute_profile_A_score(df, top_n, thresholds)
                    (profiles/profile_a.py — weighted composite + rank)
                                │
                                v
                    format for export ─> write Excel ─> print summary
```

`main.py` stays a thin orchestrator: it loads data, calls
`build_concept_scores()`, then looks up the registered filter/scorer
for whatever `profile_name` was requested (`PROFILE_FILTERS["A"]`,
`PROFILE_SCORERS["A"]`) so adding Profile B/C later requires no
changes to `main.py` beyond one import line.

---

## 3. Two-Layer Weighting Model

Weighting happens in two independent layers, both YAML-configurable:

| Layer | Controls | Lives in | Example |
|---|---|---|---|
| **Concept-level** (`concept_weights`) | How much each raw metric counts *within* its own concept score | `scoring.py`, each `calculate_*_score()` function | `performance.return_3y: 0.40` |
| **Profile-level** (`weights`) | How much each of the 8 concept scores counts *relative to each other* | `profiles/profile_a.py::compute_profile_A_score()` | `weights.performance: 0.25` |

Both layers default to values baked into `config.py`
(`DEFAULT_CONCEPT_WEIGHTS`, `PROFILE_A_WEIGHTS`), and both can be
partially overridden from the profile's YAML file without needing to
repeat every sibling key (see Section 6).

---

## 4. The 8 Scored Concepts (+ 3 Unscored Flag Groups)

Of the 11 originally-discussed concept groups, **8 are implemented as
0-100 scores**, all normalized WITHIN Morningstar Category (not
globally) via `scoring.normalize_within_category()`. Category-relative
normalization was chosen because volatility/return/tracking-error
behavior varies a lot by category, and a global min-max would unfairly
penalize inherently higher-risk categories.

| # | Concept | Function | Default column weights | Direction |
|---|---|---|---|---|
| 1 | Performance & Return | `calculate_performance_score()` | return_3y 0.40, return_5y 0.35, return_1y 0.10, rank_3y 0.15 | higher = better |
| 2 | Risk-Adjusted Return | `calculate_risk_adjusted_score()` | sharpe_3y 0.45, sharpe_1y 0.10, upside 0.25, downside 0.20 | higher = better (downside capture inverted) |
| 3 | Volatility & Downside Risk | `calculate_volatility_score()` | stdev_3y 0.45, drawdown_3y 0.30, drawdown_5y 0.25 | lower = better (inverted) |
| 4 | Tracking Quality | `calculate_tracking_score()` | tracking_error_3y 0.65, tracking_error_1y 0.35 | lower = better (inverted) |
| 5 | Liquidity & Size | `calculate_liquidity_size_score()` | fund_size 0.60, trading_volume 0.40 | higher = better |
| 6 | Quality & Valuation | `calculate_quality_valuation_score()` | growth_grade 0.35, financial_health 0.35, price_fair_value 0.30 | higher = better (price/fair value inverted) |
| 7 | Costs & Fees | `calculate_costs_score()` | net_expense_ratio 0.75, management_fee 0.25 | lower = better (inverted) |
| 8 | Tax & Income | `calculate_tax_income_score()` | tax_cost_ratio 0.55, sec_yield 0.45 | tax cost inverted, yield not |

**Not yet scored (left as raw/flag columns, per explicit decision):**

| # | Concept | Function | Current behavior |
|---|---|---|---|
| 9 | Sector / Exposure | `build_sector_exposure_flags()` | placeholder, passthrough only |
| 10 | Manager & Stewardship | `build_manager_stewardship_flags()` | adds `Flag_New_Manager` (tenure < 2Y) |
| 11 | Structure & Flags | `build_structure_flags()` | adds `Flag_Leveraged_Fund`, `Flag_Interval_Fund`, `Flag_Fund_of_Funds`, `Flag_Tender_Offer` |

These three are intentionally NOT folded into the 0-100 composite score
yet. Concepts 10 and 11 ARE consumed today, but only as **hard
eligibility filters** (Section 5), not as weighted scores — this was a
deliberate choice: a leveraged or interval fund shouldn't be *ranked
lower*, it should be *excluded entirely* for a low-risk profile.

---

## 5. Eligibility Filters (`apply_profile_A_filters`)

Applied BEFORE scoring/ranking. All configurable via YAML `thresholds`,
all default to sensible values if omitted:

| Filter | Default | Rationale |
|---|---|---|
| `require_category` | `true` | Can't rank within-category without one |
| `max_expense_ratio` | `0.75` | Cost ceiling |
| `require_fund_size` | `true` | Avoid closure risk |
| `require_3y_return` | `true` | Avoid funds without a full track record |
| `exclude_leveraged_funds` | `true` | Leverage = structurally higher risk |
| `exclude_interval_funds` | `true` | Illiquid structure |
| `exclude_tender_offer_funds` | `true` | Illiquid/uncertain redemption structure |

Each filter prints a before/after row count so the console output
doubles as an audit trail of exactly why funds were dropped.

---

## 6. YAML Configuration & Defaulting Strategy

**File:** `input_files/input_profile_a.yaml`

The loading pipeline (`input_file.py::load_profile_input()`) does NOT
just `dict.get()` at scattered call sites. Instead:

1. `config.py` defines one canonical schema, `DEFAULT_THRESHOLDS`,
   containing every known key (filters, `weights`, `concept_weights`)
   with sensible defaults.
2. `input_file.deep_merge_dicts(defaults, overrides)` recursively
   merges the user's YAML onto `DEFAULT_THRESHOLDS` — nested dicts are
   merged key-by-key, not replaced wholesale.
3. This means a user can override a SINGLE leaf value (e.g. only
   `concept_weights.performance.return_3y`) and every sibling key
   they didn't repeat (`return_5y`, `return_1y`, `rank_3y`, and every
   other concept block) still falls back to its default automatically.
4. Unknown/misspelled top-level keys trigger a console warning (likely
   typo) rather than failing silently.

This was a direct response to the stated goal: *"I like the idea to
configure the value in input yaml, [because] I'm learning each
column's meaning and [want] to find the best weight for it"* — i.e.
support safe, incremental, single-value tuning without needing to
re-type entire weight blocks each time.

---

## 7. Current Weight Values (as configured today)

**Profile-level (`weights`, sums to 1.0):**

| Concept | Weight |
|---|---|
| Performance | 0.25 |
| Risk-Adjusted | 0.20 |
| Volatility | 0.15 |
| Costs | 0.15 |
| Quality/Valuation | 0.10 |
| Tracking | 0.05 |
| Liquidity/Size | 0.05 |
| Tax/Income | 0.05 |

**Concept-level (`concept_weights`, each block sums to 1.0):** see
Section 4 table above — currently set to each function's own built-in
default values (no leaf overrides applied yet).

---

## 8. Scoring & Ranking Output Columns

Added by `compute_profile_A_score()`:

- `Profile_A_Score` — the final weighted composite (0-100 scale)
- `Profile_A_Rank_In_Category` — rank within Morningstar Category
- `Profile_A_Selected_Flag` — `True` if rank ≤ `top_n_per_category`
- `Profile_A_Rank_Overall` — rank across the entire eligible universe
- `Profile_A_Selected_Overall_Flag` — `True` if overall rank ≤ top_n

Missing concept scores for a given fund are excluded from that row's
weighted average (weights re-normalize across only the non-NaN
concepts present), so one missing metric doesn't zero out a fund's
entire score.

---

## 9. Known Open Items / Not Yet Decided

- Whether Sector/Exposure, Manager & Stewardship, and Structure &
  Flags should eventually become weighted scores rather than
  pure filters/flags.
- Whether `Flag_New_Manager` should become an eligibility filter
  (like the structural flags) or stay informational-only.
- Exact weight tuning — current values are reasonable starting
  points, not yet validated against real historical selections.
- `pyyaml` is not yet confirmed installed in the user's real Python
  environment (separate from this sandbox) — needs verification
  before `main.py` can run end-to-end.
- Profile B/C do not exist yet; the registry pattern
  (`PROFILE_FILTERS`, `PROFILE_SCORERS`) is ready for them.

---

## 10. File Map

| File | Role |
|---|---|
| `config.py` | `DEFAULT_THRESHOLDS`, `DEFAULT_CONCEPT_WEIGHTS`, `PROFILE_A_WEIGHTS`, grade mappings |
| `input_file.py` | YAML loading, `deep_merge_dicts()`, `ProfileInput` dataclass |
| `scoring.py` | `normalize_within_category()`, 8 `calculate_*_score()` functions, 3 flag builders, `build_concept_scores()`, profile registry decorators |
| `profiles/profile_a.py` | `apply_profile_A_filters()`, `compute_profile_A_score()` |
| `main.py` | Thin orchestrator: load → merge → score → filter → rank → export |
| `input_files/input_profile_a.yaml` | Profile A's run configuration |
