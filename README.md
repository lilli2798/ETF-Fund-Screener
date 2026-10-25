# ETF Fund Screener

A Python tool that scores and ranks ETFs and mutual funds from Morningstar exports, adds Yahoo Finance metrics, calendar-year returns and performance in past market crises, and writes everything into **one Excel sheet** per run. A GitHub Actions job runs it every night and emails you the report.

## What This Tool Does

- **Scores every fund (0-100) on 9 concepts** and ranks it within its Morningstar Category and overall
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
python main.py        # asks for the profile file, e.g. input_files/input_profile_a.yaml
python run_ci.py      # same, without prompts (uses input_files/input_profile_a.yaml)
```

### Output (in `output/etf_screener/`, not stored in git)
- `results_profile_A_<date-time>.xlsx` - the report (one row per fund, benchmark rows at the bottom)
- `results_profile_A_<date-time>_by_category/` - one subfolder each for Asset Class, Morningstar Category, Yahoo sub-sector and Style Box, with one file per group
- `results_profile_A_<date-time>_used_weights.yaml` - the exact weights used for that run
- `run_recorder.yaml` - settings of every run, the funds missing yearly data, and how many funds have volatile-period data
- Local runs also save results to the SQLite database `data/etf_screener.db` (kept on your computer only)

## Configuration

Everything is set in the profile YAML (`etf_screener/input_files/input_profile_a.yaml`); anything you leave out falls back to the defaults in `etf_screener/config.py`.

```yaml
profile: A
data_path: data/                 # Morningstar exports
out_path: ../output/etf_screener # where results go
thresholds:
  max_expense_ratio: 1.75
  exclude_leveraged_funds: false
  min_initial_investment: 50000
  weights:                       # how much each concept counts (should sum to ~1.0)
    long_term_return_performance: 0.25
    short_term_return_performance: 0.10
    risk_adjusted: 0.20
    volatility: 0.15
    tracking: 0.05
    liquidity_size: 0.05
    quality_valuation: 0.15
    costs: 0.10
    tax_income: 0.00
  concept_weights:               # how much each metric counts inside a concept
    risk_adjusted:
      sharpe_3y: 0.45
      ...
```

- **Concepts** (all scored 0-100 *within* each Morningstar Category): long-term returns (1Y-20Y), short-term returns (1W-YTD), risk-adjusted (Sharpe, capture ratios, Yahoo Sharpe/Z-scores), volatility (std dev, drawdowns), tracking error, liquidity & size, quality & valuation (grades, Medalist, stars, price/fair value, moat), costs, tax & income.
- **`concept_weights` must list every metric of a concept.** To drop one, set it to `0.0` rather than deleting it - a missing key stops the run with a clear error.
- **Morningstar's long-term preset** is available as `MORNINGSTAR_LONG_TERM_WEIGHTS` / `MORNINGSTAR_CONCEPT_WEIGHTS` in `config.py`, and as commented examples in the YAML.
- **Missing data doesn't penalize a fund**: scores are averaged over the metrics it has.

## Reading the Report

| Columns | Meaning |
|---|---|
| Morningstar data | Everything from your exports |
| `... Score` concept columns | Each concept, 0-100 within category |
| `Profile A Score`, `Rank In Category`, `Rank Overall`, `Selected Flag` | Final score; selected = top N (default 5) in its category |
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

- **New year**: the GitHub job adds last year's returns for every ticker in the CSV on **January 2** - nothing to do.
- **New fund**: if the screener prints
  `Missing - not in yearly file (add to yahoo_returns/sources/tickers.txt ...): NEWTKR`,
  put `NEWTKR` in `yahoo_returns/sources/tickers.txt` (it may contain only the new tickers) and run
  ```bash
  python etf_screener/yahoo_returns/yearly_cache_manager.py
  ```
  then commit the updated CSV. Tickers already in the CSV are skipped; empty rows are retried.

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

## Automation (GitHub Actions)

| Workflow | When | What it does |
|---|---|---|
| **Daily ETF Screener** | every night (00:00 UTC) | Runs `run_ci.py`, emails / Slacks the selected funds (`alerts.py`), commits the sub-sector and volatile caches, attaches the report to the run |
| **Update Yearly Returns Cache** | January 2 (or run manually) | Adds last year's returns and any new tickers to the yearly CSV and commits it |
| **Cleanup Workflow Runs** | 1st of each month | Keeps the last 10 runs of each workflow |

- Email / Slack settings are GitHub secrets: `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USERNAME`, `EMAIL_PASSWORD`, `EMAIL_FROM`, `EMAIL_TO`, `SLACK_WEBHOOK_URL`.
- GitHub starts from an empty machine each run, so the **caches it needs are committed to git**: `utils/sector_cache.json`, `yahoo_returns/sources/etf_yearly_history.csv` and `etf_volatile_history.csv`. Reports and databases are not.
- The Morningstar exports are **not** in git; the daily job uses a copy saved in the GitHub Actions cache.

## Project Structure

```
ETF-Fund-Screener/
├── etf_screener/
│   ├── main.py                 # Entry point (asks for the profile YAML)
│   ├── run_ci.py               # Same pipeline without prompts (GitHub)
│   ├── alerts.py               # Email / Slack of selected funds (GitHub)
│   ├── config.py               # Defaults, weights, paths
│   ├── input_file.py           # Loads the profile YAML
│   ├── data_loading.py         # Reads and merges the Morningstar exports
│   ├── merging.py              # Fund filter, yearly return columns
│   ├── scoring.py              # Concept scores
│   ├── profiles/profile_a.py   # Profile A filters and final score
│   ├── performance.py          # Yearly stats, volatile periods, benchmark rows
│   ├── export.py               # Excel output and run_recorder.yaml
│   ├── database.py             # Local SQLite results database
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
│   │   └── sources/                  # tickers.txt, etf_yearly_history.csv, etf_volatile_history.csv
│   ├── standalone_utils/       # Hand-run tools, not used by the screener
│   │   ├── query_results.py, import_excel.py   # Search / import into the local database
│   │   ├── compare_results.py                  # Compare selections across result files
│   │   ├── get_yahoo_dta.py                    # Yahoo metrics for a watchlist (tickers.txt)
│   │   └── customized_query_returns.py, ...    # Older custom date-range tool
│   ├── input_files/input_profile_a.yaml
│   ├── docs/                   # Glossary, column dictionary, Profile A design, database schema
│   └── data/                   # Your Morningstar exports (not in git)
├── .github/workflows/          # Daily, yearly and cleanup jobs
├── eTrade/                     # eTrade-specific scripts
├── output/                     # Reports (not in git)
├── data/etf_screener.db        # Local results database (not in git)
└── requirements.txt
```

## Data Sources

- **Morningstar** - fund data, ratings and returns (Excel exports)
- **Yahoo Finance** - sub-sectors, Sharpe ratios, yearly and volatile-period returns, index data

## Known Limitations

- **Indexes are price-only, funds include dividends**, so funds look about 1-2 points/year better than the indexes in the yearly and crisis comparisons (e.g. 2025: SPY 18.9% vs ^GSPC 17.5%).
- **Yearly returns for 2006-2025 end on Dec 30** instead of Dec 31 (an old download bug, since fixed); 2026 onward is correct. A full rebuild of the yearly CSV would correct the older years.
- **Yahoo sub-sectors come from a fund's top 10 holdings** (the most Yahoo lists) and are re-checked about once a year; new funds are looked up the night they appear. Set `force_refresh_subsector: true` in `yahoo_metrics` for one run to refresh them all. Broad funds can change sub-sector between lookups, which moves their Z-scores.
- **Only Profile A** (long-term, low-risk) is implemented; new profiles can be added in `profiles/`.
- **The GitHub job screens its cached copy of your exports**, not your latest local files.

## Documentation

- `etf_screener/docs/column_glossary.md` - definitions and formulas for all metrics
- `etf_screener/docs/report_column_dictionary.xlsx` - what every report column means: definition, formula, optimal value, caveats, and its weight in Profile A (rebuild with `python docs/build_column_dictionary.py` after changing weights)
- `etf_screener/docs/profile_a_design.md` - Profile A design
- `etf_screener/docs/database_schema.md` - local database tables
