# ETF Fund Screener

A Python tool that scores and ranks ETFs and mutual funds from Morningstar exports, adds Yahoo Finance metrics, calendar-year returns and performance in past market crises, and writes everything into **one Excel sheet** per run. A GitHub Actions job runs it every night and emails you the report.

## What This Tool Does

- **Scores every fund (0-100) on 10 concepts** (returns, risk-adjusted return, volatility, resilience in crashes and calendar years, costs, quality, ...) and ranks it within its Morningstar Category and overall
- **Filters out funds** that don't meet your rules (expense ratio, loads, minimum investment, leveraged funds, ...)
- **Adds Yahoo Finance metrics**: sub-sector, Sharpe ratio (1Y/3Y) and sub-sector Z-scores
- **Adds the last 10 calendar-year returns** and how often each fund beat or trailed the major indexes
- **Adds performance in 24 volatile market periods since 1976** (crash and recovery returns)
- **Shows the benchmarks** (S&P 500, Dow Jones, NASDAQ) at the bottom of the report for comparison
- **Runs nightly on GitHub** and sends the selected funds by email / Slack

## Quick Start

### Install
```bash
pip install -r requirements.txt
```

### Input data
Put your Morningstar Excel exports in `etf_screener/data/`. Each export is usually downloaded as several **views of the same fund list**, for example:

| File | Contains |
|---|---|
| `d-all.xlsx` | category, expense ratio, asset class, grades, dividends... |
| `d-all (1).xlsx` | returns, risk, alpha, Sharpe, drawdowns... |
| `d-all (2).xlsx` | Medalist and Morningstar Star ratings |

Keep all of them: the screener merges every file in the folder by **Ticker**. Individual stocks are dropped automatically (rows without a `Share Class Type`).

### Run
```bash
cd etf_screener
python main.py        # asks for a profile file; press Enter to run all profiles into one report
python run_ci.py      # no prompts; every input_files/profile_*.yaml into one report
```

### Output (in `output/etf_screener/`, not stored in git)
- `results_profile_LT_ST_<date-time>.xlsx` - one row per fund (benchmark rows at the bottom) with both `Profile LT ...` and `Profile ST ...` score/rank columns. Every fund gets a score from every profile; the concept-score columns are LT's. Running a single YAML in `main.py` gives `results_profile_<LT|ST>_...` with just that profile.
- `results_profile_LT_ST_<date-time>_by_category/` - one subfolder each for Asset Class, Morningstar Category, Yahoo sub-sector and Style Box, with one file per group
- `results_profile_LT_ST_<date-time>_used_weights_<LT|ST>.yaml` - the exact weights each profile used
- `run_recorder.yaml` - settings of every run, the funds missing yearly data, and how many funds have volatile-period data
- Only the newest 10 reports are kept; each run deletes older ones (with their files and recorder entries). Change `KEEP_LAST_REPORTS` in `config.py` (None = keep all). `db_access/query.py` reads the kept reports as the `reports` table

## Configuration

Each profile is one `etf_screener/input_files/profile_*.yaml`, and the YAML is the only place its settings live. Every key must be there: a missing or misspelled one stops the run with the file and key named, instead of quietly using a hidden default. `config.py` holds only project-wide settings (the eTrade columns to load, benchmark indexes, grade mappings, `KEEP_LAST_REPORTS`), including `PURCHASE_RULES`: no front or deferred load, no redemption fee, and at most a $50,000 minimum initial investment. Those apply to every profile and remove funds before any scoring. Leveraged funds are kept and scored.

| Profile | YAML | Ranks funds by |
|---|---|---|
| `LT` | `profile_long_term.yaml` | Long-term, low-risk, steady returns |
| `ST` | `profile_short_term.yaml` | Short-term momentum (1M-6M returns, 1Y risk-adjusted return) |

Both share the scoring code in `profiles/weighted_profile.py`; only their YAML weights differ. Every fund is ranked, so the highest rank numbers in a profile's columns are its weakest funds.

**Adding a profile:** copy a YAML to `input_files/profile_<name>.yaml` and change `profile:` (e.g. `INC`). `run_ci.py`, `main.py` (Enter) and the column dictionary pick it up, and the report gets `Profile INC ...` columns; no code changes. Add `enabled: false` to keep a YAML without running it. Profile YAMLs only **score** funds; they never remove one, so every fund in the report has a score from every profile and the order of the files doesn't matter. To make something not count, set its weight to `0.0` (the expense ratio, for example, counts through `weights: costs`). The concept-score columns (Volatility Score, ...) are the first profile's (`profile_long_term`, by file name).

```yaml
profile: LT
data_path: data/                 # Morningstar exports
out_path: ../output/etf_screener # where results go
thresholds:
  weights:                       # how much each concept counts (should sum to ~1.0)
    long_term_return_performance: 0.25
    short_term_return_performance: 0.05
    risk_adjusted: 0.20
    volatility: 0.15
    resilience: 0.10             # beat the indexes in calendar years and crashes
    tracking: 0.05
    liquidity_size: 0.05
    quality_valuation: 0.10
    costs: 0.10
    tax_income: 0.00
  concept_weights:               # how much each metric counts inside a concept
    risk_adjusted:
      sharpe_3y: 0.45
      ...
```

- **Concepts** (all scored 0-100 *within* each Morningstar Category): long-term returns (1Y-20Y), short-term returns (1W-YTD), risk-adjusted (Sharpe, capture ratios, Yahoo Sharpe/Z-scores), volatility (std dev, drawdowns), tracking error, liquidity & size, quality & valuation (grades, Medalist, stars, price/fair value, moat), costs, tax & income.
- **`concept_weights` must list every metric of a concept.** To drop one, set it to `0.0` rather than deleting it - a missing key stops the run with a clear error.
- **Missing data doesn't penalize a fund**: scores are averaged over the metrics it has.

## Reading the Report

| Columns | Meaning |
|---|---|
| Morningstar data | Everything from your exports |
| `... Score` concept columns | Each concept, 0-100 within category |
| `Profile LT Score` / `Profile ST Score`, `Rank In Category`, `Rank Overall`, `Selected Flag` | Final score; selected = top `top_n_per_category` in its category, or top `top_n_overall` overall |
| `Return Rank (1W)` ... `(20Y)` | Rank of each period's return across all funds (1 = highest) |
| `Yahoo SubSector`, `Sharpe 1Y/3Y`, `Z Score 1Y/3Y` | Yahoo metrics; Z-scores compare Sharpe within the same sub-sector |
| `Yearly Return (2016)` ... `(2025)` | Calendar-year returns, in percent |
| `Yearly Beat All Indexes`, `Yearly Trailed All Indexes`, `Yearly Beat %`, ... | Years the fund beat the **best** / trailed the **worst** of ^GSPC, ^DJI, ^IXIC |
| `Volatile Decline: <period>` | Return from the S&P 500 high to its low in that crisis |
| `Volatile Recovery: <period>` | Return from the low back to the old high (bear markets only) |
| `Volatile Beat All Indexes`, ..., `Volatile Top 10% Count` ... `Bottom 10% Count` | Same stats, based on the crisis declines |

How to read them:
- **Returns: higher is always better.** For a decline, -5 (lost 5%) is better than -30.
- **Compare counts with `Periods With Data`** - a fund launched in 2018 can only appear in a few periods. `Beat %` / `Trailed %` are already shares of the periods each fund has.
- **Percentile buckets rank your screener funds against each other**, not the whole market.
- **Benchmark rows** (`^IXIC`, `^DJI`, `^GSPC`) at the bottom show the indexes' own yearly and crisis returns. They are never scored or selected.

## Yearly Returns

Calendar-year returns live in `etf_screener/yahoo_returns/sources/etf_yearly_history.csv` (one row per ticker, one column per year since 2006). The CSV is the master list.

- **New fund**: added automatically. Each screener run downloads only the funds not in the CSV yet (like the volatile-period cache), and the nightly GitHub job commits the CSV. A fund with no complete year on Yahoo yet (e.g. launched this year) is saved as an empty row so it isn't downloaded every night.
- **New year**: the GitHub job adds last year's returns for every ticker in the CSV on **January 2**, and refills the empty rows. To do it by hand: `python etf_screener/yahoo_returns/yearly_cache_manager.py`.

## Volatile Market Periods

`etf_screener/yahoo_returns/volatile_config.yaml` lists 24 S&P 500 periods since 1976: every decline of 15% or more (bear markets and the separate waves inside them, e.g. 2001, 2008, 2022) plus the 1997 volatility spike.

- **Edit freely**: rename periods, add your own with `source: manual`, or change dates. The next screener run recalculates any new or changed period for every fund.
- **Find new periods** after a future crash: `python etf_screener/yahoo_returns/volatile_periods.py` (keeps your names and manual entries).
- **Fund returns are cached** in `yahoo_returns/sources/etf_volatile_history.csv`, so only new funds or changed periods are downloaded.

## Custom Date Ranges (interactive)

```bash
python etf_screener/yahoo_returns/user_defined_by_date_yahoo_analize.py
```
- Input: press Enter for your latest screener results, or give a `.xlsx` / `.txt` (one ticker per line - stocks work too).
- Pick a volatile period from the list, or type your own start / end dates.
- Choose year / month / week breakdowns; results go to `output/yahoo_screen/`.

## Querying the Data with SQL

`etf_screener/db_access/query.py` runs SQL (DuckDB) directly on the newest report, the eTrade exports, the yearly and volatile-period returns, and every kept report. Nothing needs importing, and new columns show up automatically. **Full guide: [`etf_screener/db_access/README.md`](etf_screener/db_access/README.md)** (picking runs by time stamp, and things to watch out for).

```bash
cd etf_screener
python db_access/query.py                       # interactive prompt; .help, .tables, .find TEXT
python db_access/query.py --find sharpe         # which columns mention "sharpe", and how to write them in SQL
python db_access/query.py top_both              # saved query in db_access/queries/
python db_access/query.py ticker_history ticker=VOO --xlsx
python db_access/query.py "SELECT Ticker, \"Profile LT Score\" FROM report ORDER BY 2 DESC LIMIT 10"
```

Tables: `report`, `report_no_yahoo`, `etrade`, `yearly_returns`, `volatile_returns`, `reports` (every saved report, with `run_time`). Spreadsheets are cached in `output/query_cache/` and re-read only when they change; Excel results go to `output/queries/`. Saved queries: `top_both`, `sell_candidates`, `category_top`, `ticker_history`, `steady_yearly`, `momentum_top` / `momentum_bottom` (the 50 funds strongest / weakest over both 1 week and 1 month, which used to be report tabs), `zscore_matrix` (funds whose 1Y and 3Y Z-scores mark them as Core, Momentum or Value dip), `beat_trail` (high Yearly Beat-Trail Diff, with the 10% bands to judge how volatile); save your own with `.save NAME` at the prompt.

## Automation (GitHub Actions)

| Workflow | When | What it does |
|---|---|---|
| **Daily ETF Screener** | every night (00:00 UTC) | Runs `run_ci.py`, emails / Slacks the funds selected in their category AND overall by both LT and ST (`ALERT_FLAGS` in `alerts.py`), commits the sub-sector, volatile and yearly caches, attaches the report to the run |
| **Update Yearly Returns Cache** | January 2 (or run manually) | Adds last year's returns to the yearly CSV, refills empty rows, and commits it |
| **Cleanup Workflow Runs** | Daily, 08:00 UTC | Keeps the last 10 runs of each workflow and the last 10 report artifacts |

- Email / Slack settings are GitHub secrets: `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USERNAME`, `EMAIL_PASSWORD`, `EMAIL_FROM`, `EMAIL_TO`, `SLACK_WEBHOOK_URL`.
- GitHub starts from an empty machine each run, so the **caches it needs are committed to git**: `utils/sector_cache.json`, `yahoo_returns/sources/etf_yearly_history.csv` and `etf_volatile_history.csv`. Reports are not.
- The Morningstar exports are **not** in git; the daily job uses a copy saved in the GitHub Actions cache.

## Project Structure

```
ETF-Fund-Screener/
├── etf_screener/
│   ├── main.py                 # Entry point (asks for the profile YAML)
│   ├── run_ci.py               # Same pipeline without prompts (GitHub)
│   ├── alerts.py               # Email / Slack of funds meeting ALERT_FLAGS (GitHub)
│   ├── config.py               # Project-wide settings (columns, benchmarks, grade maps)
│   ├── input_file.py           # Loads the profile YAML
│   ├── data_loading.py         # Reads and merges the Morningstar exports
│   ├── merging.py              # Fund filter, purchase rules, yearly return columns
│   ├── scoring.py              # Concept scores
│   ├── profiles/weighted_profile.py  # Final score and ranks (every profile YAML)
│   ├── performance.py          # Yearly stats, volatile periods, benchmark rows
│   ├── export.py               # Excel output and run_recorder.yaml
│   ├── utils/
│   │   ├── yahoo_metrics.py    # Yahoo sub-sector, Sharpe, Z-scores
│   │   └── sector_cache.json   # Cached sub-sectors (about 1 year)
│   ├── yahoo_returns/
│   │   ├── yearly_cache_manager.py   # Updates the yearly returns CSV
│   │   ├── volatile_periods.py       # Finds S&P 500 volatile periods
│   │   ├── volatile_config.yaml      # The periods used in the report
│   │   ├── benchmark_stats.py        # Shared beat/trail and percentile stats
│   │   ├── yahoo_config.py           # Settings for this folder
│   │   ├── user_defined_by_date_yahoo_analize.py  # Interactive date-range analysis
│   │   └── sources/                  # etf_yearly_history.csv, etf_volatile_history.csv
│   ├── db_access/              # SQL on reports, eTrade data and score history
│   │   └── query.py, queries/*.sql             # DuckDB queries, no import needed
│   ├── standalone_utils/       # Hand-run tools, not used by the screener
│   │   ├── compare_results.py                  # Compare selections across result files
│   │   └── yahoo_get_top_return.py, ...        # Helpers for the tools above
│   ├── input_files/            # profile_long_term.yaml, profile_short_term.yaml
│   ├── docs/                   # Glossary, column dictionary, Profile A design
│   └── data/                   # Your Morningstar exports (not in git)
├── .github/workflows/          # Daily, yearly and cleanup jobs
├── eTrade/                     # eTrade-specific scripts
├── output/                     # Reports (not in git)
└── requirements.txt
```

## Data Sources

- **Morningstar** - fund data, ratings and returns (Excel exports)
- **Yahoo Finance** - sub-sectors, Sharpe ratios, yearly and volatile-period returns, index data

## Known Limitations

- **Indexes are price-only, funds include dividends**, so funds look about 1-2 points/year better than the indexes in the yearly and crisis comparisons (e.g. 2025: SPY 18.9% vs ^GSPC 17.5%).
- **Yearly returns for 2006-2025 end on Dec 30** instead of Dec 31 (an old download bug, since fixed); 2026 onward is correct. A full rebuild of the yearly CSV would correct the older years.
- **Yahoo sub-sectors come from a fund's top 10 holdings** (the most Yahoo lists) and are re-checked about once a year; new funds are looked up the night they appear. Set `force_refresh_subsector: true` in `yahoo_metrics` for one run to refresh them all. Broad funds can change sub-sector between lookups, which moves their Z-scores.
- **Profiles only score, they never filter**: LT and ST differ only in their YAML weights. Rules for every profile are `PURCHASE_RULES` in `config.py`; a profile that needs its own filter needs its own module in `profiles/`.
- **The GitHub job screens its cached copy of your exports**, not your latest local files.

## Documentation

- `etf_screener/docs/report_column_dictionary.xlsx` - what every report column means: definition, formula, optimal value, caveats, and its weight in the long-term profile; also a sector reference tab (rebuild with `python docs/build_column_dictionary.py` after changing weights; add `input_files/profile_short_term.yaml` for the short-term weights)
