# Column Glossary & Formula Reference

*Definitions, formulas, and sector-composition risk notes for every
raw column consumed by the ETF screener, organized by the 8 scored
concept groups (+ 3 unscored ones). Written to support weight-tuning
work -- i.e. understanding what drives each number before deciding how
much it should count.*

---

## 0. Important caveat confirmed: Morningstar sector granularity

**Your suspicion is correct.** Morningstar's Technology sector does
NOT separate software from hardware. Per Morningstar's own sector
definition, "Technology" bundles together companies that design
operating systems and applications (software) AND companies that
manufacture computer equipment, data storage, networking gear, and
semiconductors (hardware/semis) into ONE sector bucket.

This matters for two DIFFERENT fields that are easy to conflate:

| Field | What it is | Granularity |
|---|---|---|
| **Morningstar Category** (e.g. "Technology", "Large Growth") | Fund-level classification -- describes the fund's overall investment style/focus. 127 categories total. | Coarse. A Category can contain funds with very different underlying sector/sub-industry composition. |
| **Sector** (e.g. holdings % in "Technology") | Stock-level classification of what a fund actually holds. 11 sectors, mirroring GICS. | Also coarse -- Technology sector = software + hardware + semis + networking, all combined. |

**Practical consequence for this project:** every concept score in
`scoring.py` is normalized WITHIN Morningstar Category
(`normalize_within_category()`). If two ETFs share a Category (e.g.
both "Technology") but one is semiconductor-heavy (cyclical, capital-
intensive, hardware supply-chain exposed) and the other is
enterprise-software-heavy (higher margins, more recurring revenue,
less cyclical), they are currently treated as direct peers for every
normalized score -- Performance, Volatility, Risk-Adjusted, etc. --
even though their underlying return/risk drivers differ meaningfully.
This is a real blind spot, not a hypothetical one, and it is the
core reason "Sector/Exposure" (concept #9) was deliberately left
unscored rather than folded into the composite too early -- see
Section 4 below for how it could distort each concept.

---

## 1. Performance & Return (`calculate_performance_score`)

| Column | Definition | Formula (concept) |
|---|---|---|
| `Total Return (1Y/3Y/5Y)` | Total return including price change + reinvested dividends, annualized for periods > 1Y. | \( \text{Total Return} = \left(\frac{\text{Ending NAV} + \text{Distributions}}{\text{Beginning NAV}}\right)^{1/n} - 1 \) |
| `3Y Return Rank in Category` | Fund's percentile rank vs. other funds in the SAME Morningstar Category, on 3Y total return. 1 = best. | Morningstar computes this internally; the pipeline just flips it so higher = better score. |

**Sector impact:** Total Return is the metric MOST directly driven by
sector composition. A Technology-category ETF's 3Y return is heavily
determined by whether AI/semiconductor names or legacy
enterprise-software names dominated its holdings during that window --
two sub-sectors with very different multi-year return paths. Category-
relative normalization partially helps (compares Tech funds to other
Tech funds, not to Utilities), but does NOT correct for sub-sector
timing differences within Technology itself.

---

## 2. Risk-Adjusted Return (`calculate_risk_adjusted_score`)

| Column | Definition | Formula |
|---|---|---|
| `Sharpe Ratio (1Y/3Y Monthly)` | Return earned per unit of total risk (volatility), using monthly return series. | \( \text{Sharpe} = \dfrac{R_p - R_f}{\sigma_p} \) where \(R_p\)=fund return, \(R_f\)=risk-free rate, \(\sigma_p\)=fund's standard deviation of monthly returns. |
| `Upside Capture Ratio (3Y)` | % of benchmark's UP-market return the fund captured. >100 = outperformed in up markets. | \( \text{Upside Capture} = \dfrac{\text{Fund return in up months}}{\text{Benchmark return in up months}} \times 100 \) |
| `Downside Capture Ratio (3Y)` | % of benchmark's DOWN-market return the fund captured. <100 = lost less than benchmark in down markets (better). | \( \text{Downside Capture} = \dfrac{\text{Fund return in down months}}{\text{Benchmark return in down months}} \times 100 \) |

**Sector impact:** Semiconductor-heavy holdings tend to have higher
beta and amplify both up-capture and down-capture versus a broad Tech
benchmark; software-heavy holdings tend to be comparatively more
defensive within Tech. A fund's Sharpe Ratio also embeds \(\sigma_p\)
(volatility) in the denominator, which is itself sector-composition-
driven (see Section 3) -- so this concept inherits the same blind spot.

---

## 3. Volatility & Downside Risk (`calculate_volatility_score`)

| Column | Definition | Formula |
|---|---|---|
| `Standard Deviation (3Y Monthly)` | Dispersion of monthly returns around the mean -- the classic "volatility" measure. | \( \sigma = \sqrt{\dfrac{1}{n-1}\sum_{i=1}^{n}(R_i - \bar{R})^2} \) |
| `Maximum Drawdown (3Y/5Y)` | Largest peak-to-trough decline over the period, as a %. | \( \text{Max Drawdown} = \min_{t}\left(\dfrac{\text{Value}_t}{\max_{s \le t}(\text{Value}_s)} - 1\right) \) |

**Sector impact:** This is the concept MOST vulnerable to the sector
granularity issue you flagged. Semiconductor stocks are historically
far more volatile (larger drawdowns during cyclical downturns, e.g.
2022) than large-cap enterprise software. Two ETFs in the same
"Technology" Morningstar Category could have meaningfully different
Standard Deviation and Max Drawdown purely because of their
semiconductor vs. software weighting -- not because one is a
better-managed or lower-risk fund. Normalizing within Category doesn't
fix this, because the Category itself mixes both sub-exposures.

---

## 4. Tracking Quality (`calculate_tracking_score`)

| Column | Definition | Formula |
|---|---|---|
| `Tracking Error (1Y/3Y Monthly)` | Standard deviation of the DIFFERENCE between fund return and its benchmark return -- how closely the fund follows its index. | \( \text{Tracking Error} = \sqrt{\dfrac{1}{n-1}\sum_{i=1}^{n}\left[(R_{p,i} - R_{b,i}) - \overline{(R_p - R_b)}\right]^2} \) |

**Sector impact:** Lower direct sensitivity to sector composition than
Volatility or Performance, since Tracking Error measures deviation
FROM a benchmark, not absolute risk. However, if `Primary Benchmark`
itself has a different sub-sector mix than the fund (e.g. a fund
over/underweights semis relative to its named benchmark), tracking
error will still be elevated for sector-composition reasons rather
than poor index-replication mechanics -- worth keeping in mind before
assuming high tracking error always signals "sloppy management."

---

## 5. Liquidity & Size (`calculate_liquidity_size_score`)

| Column | Definition | Formula / Notes |
|---|---|---|
| `Fund Size` / `Total Net Assets for Share Class` | Total assets under management (AUM), typically in $. | Reported directly by the fund; no derived formula. |
| `Trading Volume` | Average daily shares traded. | Reported directly (exchange data); no derived formula. |

**Sector impact:** Minimal direct link to sector composition -- size
and liquidity are more a function of a fund's popularity, marketing,
and how long it's existed than what sub-sector it holds. Some
indirect effect: hyped sub-sectors (e.g. AI-themed semiconductor ETFs)
can see AUM/volume spike faster than diversified software ETFs
purely due to investor sentiment, which could be worth flagging
separately if you ever add a "thematic hype" filter.

---

## 6. Quality & Valuation (`calculate_quality_valuation_score`)

| Column | Definition | Formula / Notes |
|---|---|---|
| `Portfolio Growth Grade` | Letter grade (A-F) summarizing the weighted growth characteristics (revenue/earnings growth) of the fund's underlying holdings. | Morningstar proprietary grade; mapped to numeric via `config.GRADE_TO_NUMERIC` in this project. |
| `Portfolio Financial Health Grade` | Letter grade summarizing balance-sheet strength (debt levels, solvency) of underlying holdings. | Same grade-to-numeric mapping. |
| `Price/Fair Value` | Ratio of current price to Morningstar's estimated intrinsic ("fair") value. >1 = trading above fair value (expensive); <1 = below (cheap). | \( \text{Price/Fair Value} = \dfrac{\text{Market Price}}{\text{Morningstar Fair Value Estimate}} \) |

**Sector impact:** HIGH. Growth Grade and Price/Fair Value are
strongly sector-driven -- software companies typically screen with
higher growth grades and richer valuations (higher Price/Fair Value)
than hardware/semiconductor companies, which tend to trade at lower
multiples due to cyclicality and capital intensity. A Tech-category
fund's Quality/Valuation score is therefore heavily influenced by its
software-vs-hardware tilt, not purely by "how good" the fund's stock
picking is.

---

## 7. Costs & Fees (`calculate_costs_score`)

| Column | Definition | Formula / Notes |
|---|---|---|
| `Net Expense Ratio` | Annual fund operating costs as a % of assets, AFTER any fee waivers. | \( \text{Net Expense Ratio} = \dfrac{\text{Total Annual Fund Operating Expenses (after waivers)}}{\text{Average Net Assets}} \) |
| `Adjusted Expense Ratio` | Similar, but may exclude certain one-time or acquired-fund fees depending on Morningstar's methodology. | Reported directly; not separately derived in this pipeline. |
| `Management Fee` | The portion of the expense ratio paid to the fund's investment adviser specifically. | Reported directly (component of Net Expense Ratio). |

**Sector impact:** Minimal. Expense ratios are driven far more by
whether a fund is passive/index vs. active, and by provider
competitive pressure, than by sub-sector composition. This is one of
the more "sector-neutral" concepts in the model.

---

## 8. Tax & Income (`calculate_tax_income_score`)

| Column | Definition | Formula |
|---|---|---|
| `Tax Cost Ratio (1Y/2Y)` | Annualized % reduction in an investor's after-tax return due to fund distributions (capital gains, dividends) being taxed. | \( \text{Tax Cost Ratio} = 1 - \dfrac{(1+\text{After-Tax Return})}{(1+\text{Pre-Tax Return})} \) |
| `SEC 30-Day Yield` | Standardized annualized yield based on the most recent 30-day period, per SEC formula -- allows apples-to-apples yield comparison across funds. | \( \text{SEC Yield} = 2\left[\left(\dfrac{a-b}{cd}+1\right)^{6}-1\right] \) where a=investment income, b=expenses, c=avg daily shares, d=max offering price per share (SEC standardized formula). |
| `SEC 7-Day Yield` | Same concept, shorter window -- typically used for money-market-like funds. | Same SEC formula, 7-day window. |
| `Potential Capital Gains Exposure` | % of fund assets that represent unrealized gains -- a proxy for future taxable distribution risk. | \( \text{PCGE} = \dfrac{\text{Unrealized Appreciation}}{\text{Total Net Assets}} \) |

**Sector impact:** Moderate. Growth-oriented sub-sectors (software)
tend to have LOWER dividend yields and historically lower turnover-
driven capital gains distributions than more mature/cyclical
hardware/semi names, which can affect both `SEC 30-Day Yield` and
`Tax Cost Ratio` independent of the fund manager's tax-efficiency
practices.

---

## 9. Sector / Exposure -- UNSCORED (`build_sector_exposure_flags`)

Currently a placeholder passthrough with no fields populated. This is
precisely where the software-vs-hardware distinction you raised would
need to be operationalized -- but the raw structural/performance data
columns loaded today (`STRUCT_NEEDED_COLS`, `PERF_NEEDED_COLS` in
`config.py`) do NOT include a sector-weight breakdown field (e.g. "%
Software", "% Semiconductors", or GICS sub-industry weights). Without
that data, this concept can't be scored quantitatively yet -- it would
require pulling additional Morningstar sector/sub-industry weighting
fields into the source Excel exports first.

---

## 10. Manager & Stewardship -- partially used (`build_manager_stewardship_flags`)

| Column | Definition | Notes |
|---|---|---|
| `Longest Manager Tenure` | Years the longest-serving current manager has run the fund. | Used today only to compute `Flag_New_Manager` (True if < 2 years) -- informational, not currently a hard filter. |
| `Fund Managers` / `Number of Fund Managers` | Names/count of current managers. | Loaded but not yet used in scoring or flags. |
| `Management Style` | Whether the fund is managed by a single manager, team, or committee. | Loaded but not yet used. |

**Sector impact:** Low direct link -- manager tenure and style are
organizational facts about the fund, not composition-driven.

---

## 11. Structure & Flags -- used as hard filters (`build_structure_flags`)

| Column | Definition | Notes |
|---|---|---|
| `Leveraged Fund` | Whether the fund uses derivatives/debt to amplify returns (e.g. 2x, 3x funds). | Hard-excluded for Profile A via `exclude_leveraged_funds`. |
| `Interval Fund` | A closed-end-like structure that only allows redemptions at scheduled intervals (illiquid). | Hard-excluded via `exclude_interval_funds`. |
| `Fund of Funds` | A fund that invests in other funds rather than directly in securities. | Loaded, flagged, but not currently excluded. |
| `Tender Offer` | Whether the fund has an active tender offer (a structural liquidity mechanism, often signals limited redemption). | Hard-excluded via `exclude_tender_offer_funds`. |

**Sector impact:** None directly -- these are structural/legal wrapper
characteristics, independent of what the fund holds.

---

## Summary: Sector-Composition Risk Ranking

Ranking the 8 scored concepts by how much their category-relative
normalization could be distorted by within-category sector/sub-sector
mix (e.g. software vs. hardware within "Technology"):

| Rank | Concept | Distortion risk | Why |
|---|---|---|---|
| 1 | Volatility & Downside Risk | **High** | Std Dev / Max Drawdown directly reflect sub-sector cyclicality (semis >> software) |
| 2 | Quality & Valuation | **High** | Growth Grade / Price-Fair-Value systematically differ software vs. hardware |
| 3 | Performance & Return | **Medium-High** | Multi-year returns diverge a lot by sub-sector timing |
| 4 | Risk-Adjusted Return | **Medium** | Inherits volatility's distortion via the Sharpe denominator |
| 5 | Tax & Income | **Medium** | Yield/turnover differ moderately by sub-sector maturity |
| 6 | Tracking Quality | **Low-Medium** | Benchmark-relative, so partially self-correcting |
| 7 | Liquidity & Size | **Low** | Driven more by popularity/age than composition |
| 8 | Costs & Fees | **Low** | Driven mostly by passive-vs-active status, not composition |

---

## Summary: Category Dependence of the 8 Scored Concepts

A second way to think about the same 8 scored concepts is not just
"how distorted are they by sub-industry mix?" but a more basic
question: **do they conceptually depend on Morningstar Category at
all?** In other words, if we ignored Category/Sub-category entirely,
which concepts would still make sense on their own?

| Concept | Related to Morningstar Category at all? | Related to sub-category / dominant industry? | Implication for future normalization logic |
|---|---|---|---|
| Costs & Fees | **No** | **No** | Safest concept to leave completely outside any Category/Sub-industry adjustment logic. |
| Liquidity & Size | **No** | **No** | Also safe to leave outside Category/Sub-industry adjustment; mainly driven by fund age, popularity, and provider scale. |
| Tracking Quality | **Yes** | **Low** | Benchmark selection is category/style-related, but dominant-industry mix is only a secondary driver. |
| Tax & Income | **Yes** | **Moderate** | Yield/distribution behavior differs by sector maturity and sub-industry composition. |
| Risk-Adjusted Return | **Yes** | **Moderate** | Depends partly on volatility, so it inherits some of the same sub-industry distortion. |
| Performance & Return | **Yes** | **Medium-High** | Multi-year returns are heavily shaped by sub-industry timing/cycles. |
| Quality & Valuation | **Yes** | **High** | Growth/valuation characteristics differ systematically across sub-industries. |
| Volatility & Downside Risk | **Yes** | **High** | Most directly distorted by cyclicality differences between sub-industries (e.g. semis vs. software). |

**Practical takeaway from this second classification:** the sub-
industry-aware improvement work does NOT need to touch all 8 scored
concepts. The clearest candidates to leave alone are **Costs & Fees**
and **Liquidity & Size**. The clearest candidates for future
Category+Sub-industry-aware normalization are **Volatility & Downside
Risk**, **Quality & Valuation**, **Performance & Return**, and then
possibly **Risk-Adjusted Return** as a second-order follow-up.

**Practical takeaway:** before finalizing weights for Volatility,
Quality/Valuation, or Performance in a sector-heavy Morningstar
Category like Technology, it would be worth manually spot-checking a
few ETFs' actual sub-sector holdings (e.g. via each fund's factsheet)
rather than trusting Category-relative normalization alone to make
them comparable.
