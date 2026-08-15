# ETF Screener Database Schema

## Overview

This database stores historical ETF screener results with full history tracking capabilities. The schema is designed to support:

- **History tracking**: Each screener run creates new records without overwriting previous data
- **Efficient queries**: Separate tables for different data types enable fast analysis
- **Flexibility**: Easy to add new metrics without schema changes
- **Normalization**: Static fund data stored once and referenced by ticker

## Storage Strategy

The system uses a **hybrid approach**:

- **Database**: Authoritative source for all historical data with full query capabilities
- **run_recorder.yaml**: Lightweight cache of recent runs for quick inspection and debugging

## Tables

### 1. runs

Stores metadata for each screener run. This table replaces the historical tracking in `run_recorder.yaml`.

| Column | Type | Description |
|--------|------|-------------|
| run_id | TEXT (PK) | Unique identifier for each run (format: `profile_name_YYYYMMDD_HHMMSS`) |
| run_timestamp | DATETIME | When the screener run was executed |
| profile_name | TEXT | Name of the profile used (e.g., "A", "B") |
| weights_used | TEXT (JSON) | Profile-level weights dictionary |
| concept_weights | TEXT (JSON) | Column-level concept weights dictionary |
| total_funds_count | INTEGER | Total number of funds in the dataset |
| selected_funds_count | INTEGER | Number of funds that passed all filters |

```sql
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    run_timestamp DATETIME,
    profile_name TEXT,
    weights_used TEXT,
    concept_weights TEXT,
    total_funds_count INTEGER,
    selected_funds_count INTEGER
);
```

### 2. funds

Stores relatively static fund information from Morningstar. Updated infrequently (e.g., annually).

| Column | Type | Description |
|--------|------|-------------|
| ticker | TEXT (PK) | ETF ticker symbol (unique identifier) |
| name | TEXT | Fund name |
| morningstar_category | TEXT | Morningstar category classification |
| asset_class | TEXT | Asset class (e.g., "Equity", "Fixed Income") |
| inception_date | TEXT | Fund inception date |
| primary_benchmark | TEXT | Primary benchmark index |
| equity_style_box | TEXT | Equity style box classification |
| growth_grade | TEXT | Portfolio growth grade (A-F) |
| financial_health_grade | TEXT | Portfolio financial health grade (A-F) |
| profitability_grade | TEXT | Portfolio profitability grade (A-F) |
| price_fair_value | TEXT | Price vs Morningstar's fair value estimate |
| economic_moat_wide | TEXT | Portfolio economic moat coverage (wide) |
| last_updated | TIMESTAMP | When this fund information was last updated |

```sql
CREATE TABLE funds (
    ticker TEXT PRIMARY KEY,
    name TEXT,
    morningstar_category TEXT,
    asset_class TEXT,
    inception_date TEXT,
    primary_benchmark TEXT,
    equity_style_box TEXT,
    growth_grade TEXT,
    financial_health_grade TEXT,
    profitability_grade TEXT,
    price_fair_value TEXT,
    economic_moat_wide TEXT,
    last_updated TIMESTAMP
);
```

### 3. fund_scores

Stores historical composite scores for each fund per run.

| Column | Type | Description |
|--------|------|-------------|
| run_id | TEXT (PK) | Foreign key to runs.run_id |
| ticker | TEXT (PK) | Foreign key to funds.ticker |
| profile_score | REAL | Overall profile score (0-100) |
| rank_in_category | INTEGER | Rank within Morningstar category |
| rank_overall | INTEGER | Overall rank across all funds |
| selected_flag_category | BOOLEAN | Whether fund is selected within category |
| selected_flag_overall | BOOLEAN | Whether fund is selected overall |

```sql
CREATE TABLE fund_scores (
    run_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    profile_score REAL,
    rank_in_category INTEGER,
    rank_overall INTEGER,
    selected_flag_category BOOLEAN,
    selected_flag_overall BOOLEAN,
    PRIMARY KEY(run_id, ticker),
    FOREIGN KEY (run_id) REFERENCES runs(run_id),
    FOREIGN KEY (ticker) REFERENCES funds(ticker)
);
```

### 4. concept_scores

Stores historical concept scores for each fund per run.

| Column | Type | Description |
|--------|------|-------------|
| run_id | TEXT (PK) | Foreign key to runs.run_id |
| ticker | TEXT (PK) | Foreign key to funds.ticker |
| long_term_return_performance_score | REAL | Long-term return performance score (0-100) |
| short_term_return_performance_score | REAL | Short-term return performance score (0-100) |
| risk_adjusted_score | REAL | Risk-adjusted score (0-100) |
| volatility_score | REAL | Volatility score (0-100) |
| tracking_score | REAL | Tracking score (0-100) |
| liquidity_size_score | REAL | Liquidity/size score (0-100) |
| quality_valuation_score | REAL | Quality/valuation score (0-100) |
| costs_score | REAL | Costs score (0-100) |
| tax_income_score | REAL | Tax/income score (0-100) |

```sql
CREATE TABLE concept_scores (
    run_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    long_term_return_performance_score REAL,
    short_term_return_performance_score REAL,
    risk_adjusted_score REAL,
    volatility_score REAL,
    tracking_score REAL,
    liquidity_size_score REAL,
    quality_valuation_score REAL,
    costs_score REAL,
    tax_income_score REAL,
    PRIMARY KEY(run_id, ticker),
    FOREIGN KEY (run_id) REFERENCES runs(run_id),
    FOREIGN KEY (ticker) REFERENCES funds(ticker)
);
```

### 5. additional_metrics

Stores historical additional metrics for each fund per run.

| Column | Type | Description |
|--------|------|-------------|
| run_id | TEXT (PK) | Foreign key to runs.run_id |
| ticker | TEXT (PK) | Foreign key to funds.ticker |
| better_worst_diff | REAL | Difference between best and worst performance |
| better_pct | REAL | Percentage of better performance periods |
| worst_pct | REAL | Percentage of worst performance periods |
| worst_three_month_return | REAL | Worst three-month return value |

```sql
CREATE TABLE additional_metrics (
    run_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    better_worst_diff REAL,
    better_pct REAL,
    worst_pct REAL,
    worst_three_month_return REAL,
    PRIMARY KEY(run_id, ticker),
    FOREIGN KEY (run_id) REFERENCES runs(run_id),
    FOREIGN KEY (ticker) REFERENCES funds(ticker)
);
```

## Indexes

For efficient querying, the following indexes are recommended:

```sql
CREATE INDEX idx_runs_timestamp ON runs(run_timestamp);
CREATE INDEX idx_runs_profile ON runs(profile_name);
CREATE INDEX idx_fund_scores_ticker ON fund_scores(ticker);
CREATE INDEX idx_concept_scores_ticker ON concept_scores(ticker);
CREATE INDEX idx_additional_metrics_ticker ON additional_metrics(ticker);
```

## Example Queries

### Get recent runs
```sql
SELECT run_id, run_timestamp, profile_name, total_funds_count, selected_funds_count
FROM runs
ORDER BY run_timestamp DESC
LIMIT 10;
```

### Compare Better Worst Diff between two runs
```sql
SELECT 
    a.ticker,
    a.better_worst_diff as old_value,
    b.better_worst_diff as new_value,
    b.better_worst_diff - a.better_worst_diff as increase,
    ra.run_timestamp as old_run_date,
    rb.run_timestamp as new_run_date
FROM additional_metrics a
JOIN additional_metrics b ON a.ticker = b.ticker
JOIN runs ra ON a.run_id = ra.run_id
JOIN runs rb ON b.run_id = rb.run_id
WHERE ra.run_timestamp < rb.run_timestamp
  AND b.better_worst_diff > a.better_worst_diff
ORDER BY increase DESC
LIMIT 20;
```

### Get fund performance history
```sql
SELECT 
    r.run_timestamp,
    fs.profile_score,
    cs.long_term_return_performance_score,
    cs.short_term_return_performance_score
FROM fund_scores fs
JOIN concept_scores cs ON fs.run_id = cs.run_id AND fs.ticker = cs.ticker
JOIN runs r ON fs.run_id = r.run_id
WHERE fs.ticker = 'AAAU'
ORDER BY r.run_timestamp DESC;
```

### Find funds with improving scores
```sql
SELECT 
    a.ticker,
    a.profile_score as old_score,
    b.profile_score as new_score,
    b.profile_score - a.profile_score as improvement
FROM fund_scores a
JOIN fund_scores b ON a.ticker = b.ticker
JOIN runs ra ON a.run_id = ra.run_id
JOIN runs rb ON b.run_id = rb.run_id
WHERE ra.run_timestamp < rb.run_timestamp
  AND b.profile_score > a.profile_score
ORDER BY improvement DESC
LIMIT 10;
```

## Terminal Usage

### Open database
```bash
sqlite3 data/etf_screener.db
```

### Interactive mode with formatting
```bash
sqlite3 data/etf_screener.db
.mode column
.headers on
SELECT * FROM runs ORDER BY run_timestamp DESC LIMIT 5;
```

### One-liner queries
```bash
sqlite3 data/etf_screener.db "SELECT run_id, run_timestamp FROM runs ORDER BY run_timestamp DESC LIMIT 5;"
```

### Export to CSV
```bash
sqlite3 data/etf_screener.db -header -csv "SELECT * FROM fund_scores WHERE run_id = 'profile_A_20260814_085704'" > scores.csv
```

## Design Decisions

### Composite Primary Keys
- Used `(run_id, ticker)` as composite PK for score tables
- Natural combination that guarantees uniqueness
- Avoids synthetic auto-increment IDs
- Simplifies joins and queries

### Ticker as Primary Key for Funds
- Tickers are unique and stable for ETFs
- Natural key eliminates need for synthetic fund_id
- Simpler joins (join directly on ticker)
- Rare ticker changes can be handled with INSERT OR REPLACE

### Hybrid Storage Strategy
- Database provides full historical query capabilities
- run_recorder.yaml remains as lightweight cache for recent runs
- Enables both programmatic access and human-readable inspection
- Reduces risk of data loss through redundancy

### Separate Tables for Different Data Types
- Normalization reduces redundancy
- Efficient queries on specific data types
- Easy to add new metrics without schema changes
- Better performance for large datasets
