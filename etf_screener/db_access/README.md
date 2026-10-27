# Querying the Screener Data with SQL

`query.py` lets you ask questions of the reports, the eTrade exports and the Yahoo
return caches with SQL, without importing anything into a database. It uses
DuckDB, which reads the Excel and CSV files directly.

## 1. How to run it

Always start from the `etf_screener` folder:

```bash
cd etf_screener
```

| What you want | Command |
|---|---|
| Interactive prompt (best for exploring) | `python db_access/query.py` |
| Run a saved query | `python db_access/query.py top_both` |
| Saved query that needs a value | `python db_access/query.py ticker_history ticker=VOO` |
| Your own SQL, one-off | `python db_access/query.py "SELECT Ticker, Name FROM report LIMIT 5"` |
| Save any result to Excel | add `--xlsx` (or `--xlsx myfile.xlsx`) to any of the above |
| Find a column by part of its name | `python db_access/query.py --find sharpe` |
| All columns of a table | `python db_access/query.py --columns report` |
| List the tables | `python db_access/query.py --tables` |

The terminal shows the first 50 rows. Use `--xlsx` (or `.xlsx` at the prompt) to
get all of them; files go to `output/queries/`.

### At the interactive prompt

```
sql> .tables                          list the tables
sql> .find expense                    columns containing "expense", and how to write them
sql> .columns report return           columns of report containing "return"
sql> .queries                         list the saved queries
sql> .run ticker_history ticker=VOO   run a saved query
sql> SELECT Ticker, Name, "Profile LT Score"
...>   FROM report ORDER BY 3 DESC LIMIT 10;      end SQL with ; (can span lines)
sql> .xlsx                            save the last result to Excel
sql> .save my_top10                   save the last SQL as queries/my_top10.sql
sql> .quit
```

## 2. The tables

| Table | What it is | One row per |
|---|---|---|
| `report` | the **newest** report's overview tab | fund |
| `report_no_yahoo` | the newest report's "No Yahoo Data" tab | fund |
| `reports` | **every** kept report stacked together, plus `run_time` and `source_file` | fund **per run** |
| `etrade` | all eTrade / Morningstar exports in `etf_screener/data/`, every column | fund |
| `yearly_returns` | calendar-year returns from Yahoo: `ticker`, `year`, `total_return` | fund per year |
| `volatile_returns` | returns in each crash / recovery period: `ticker`, `period`, `total_return` | fund per period |

## 3. Picking the right run (time stamps)

**`report` vs `reports`:**

- Use **`report`** for "what does the latest run say?" It is always exactly one
  run, so every fund appears once. All saved queries except `ticker_history` use it.
- Use **`reports`** for history and comparisons. Every fund appears once **per
  run**, so without a `run_time` filter you count each fund several times.

**`run_time`** is the date and time in the report's file name
(`results_profile_LT_ST_2026-10-26_10-58-19.xlsx` gives `2026-10-26 10:58:19`).
`source_file` is the file name itself.

```sql
-- Which runs are available?
SELECT run_time, source_file, count(*) AS funds
FROM reports GROUP BY ALL ORDER BY run_time;

-- Only the latest run (same as the report table)
SELECT * FROM reports
WHERE run_time = (SELECT max(run_time) FROM reports);

-- Only one day (if you ran it several times that day, add a time too)
SELECT * FROM reports WHERE run_time::DATE = '2026-10-26';
SELECT * FROM reports WHERE run_time = '2026-10-26 10:58:19';

-- One fund over time
SELECT run_time, "Profile LT Score", "Profile LT Rank In Category"
FROM reports WHERE Ticker = 'VOO' ORDER BY run_time;
```

**Compare the latest run with the one before it** (biggest LT score changes):

```sql
WITH runs AS (SELECT DISTINCT run_time FROM reports ORDER BY run_time DESC LIMIT 2),
     new  AS (SELECT * FROM reports WHERE run_time = (SELECT max(run_time) FROM runs)),
     old  AS (SELECT * FROM reports WHERE run_time = (SELECT min(run_time) FROM runs))
SELECT new.Ticker, new.Name,
       round(old."Profile LT Score", 1) AS lt_before,
       round(new."Profile LT Score", 1) AS lt_now,
       round(new."Profile LT Score" - old."Profile LT Score", 1) AS change
FROM new JOIN old USING (Ticker)
ORDER BY abs(change) DESC LIMIT 20;
```

**Funds newly in the LT top 5 of their category since the oldest kept run:**

```sql
SELECT Ticker, Name FROM reports
WHERE run_time = (SELECT max(run_time) FROM reports) AND "Profile LT Rank In Category" <= 5
  AND Ticker NOT IN (SELECT Ticker FROM reports
                     WHERE run_time = (SELECT min(run_time) FROM reports)
                       AND "Profile LT Rank In Category" <= 5);
```

**How far back can you go?** Only as far as the reports in `output/etf_screener/`.
The screener keeps the newest 10 (`KEEP_LAST_REPORTS` in `config.py`), so older
runs disappear from `reports`. Reports from the nightly GitHub run are not in
this folder; only runs on your own computer are.

**"Newest" for `report`** is the report file modified most recently, not the
time in its name. If you open an old report in Excel and save it, `report` will
use that one. Avoid saving over reports; when in doubt, use `reports` with
`run_time = (SELECT max(run_time) FROM reports)`, which always goes by the file name.

## 4. Things to watch out for

| Watch out for | Why | Do this |
|---|---|---|
| **Column names with spaces or symbols** | `Profile LT Score` is not a valid SQL name | Wrap them in double quotes: `"Profile LT Score"`. `.find` shows the exact form to paste |
| **Text values vs column names** | `"VOO"` means a column called VOO | Use single quotes for values: `Ticker = 'VOO'` |
| **Two return scales** | Report columns like `"Total Return (1Y)"` are percent (`14.5` = 14.5%). `yearly_returns.total_return` and `volatile_returns.total_return` are fractions (`0.145` = 14.5%) | Multiply the Yahoo tables by 100 before comparing with report columns |
| **Ticker case between tables** | Yahoo tables use lower-case `ticker`, reports use `Ticker`, and spelling can differ in case | Join with `upper(y.ticker) = upper(r.Ticker)` |
| **Picking the "best" funds** | There are no Selected columns; use the ranks (1 = best) | Write `"Profile LT Rank In Category" <= 5` or `"Profile LT Rank Overall" <= 100` |
| **Blank scores and ranks** | Benchmark rows and funds a profile couldn't score have empty `Profile ...` columns | Use `IS NULL` / `IS NOT NULL`; blanks never match `<= 5` or `> 50` |
| **Counting in `reports`** | Every fund is repeated once per run | Filter on `run_time`, or use `count(DISTINCT Ticker)` |
| **Interactive prompt left open** | A session keeps the data it already loaded | After a new screener run or new eTrade files, `.quit` and start again |
| **First query is slow** | Excel is read once, then cached in `output/query_cache/` | The first `etrade` query takes about 30 s; later ones are instant until the files change |

Example joining the report with the Yahoo yearly returns (percent on both sides):

```sql
SELECT r.Ticker, r.Name, y.year, round(y.total_return * 100, 1) AS return_pct
FROM report r
JOIN yearly_returns y ON upper(y.ticker) = upper(r.Ticker)
WHERE r."Profile LT Rank Overall" <= 100
ORDER BY r.Ticker, y.year DESC;
```

## 5. Saved queries

Saved queries are the `.sql` files in `db_access/queries/`. The first `--` line is
the description shown by `.queries`.

| Query | What it shows | Needs |
|---|---|---|
| `top_both` | funds in the top 5 of their category for both LT and ST | optional: `top=5` |
| `sell_candidates` | weakest 3 funds per category on both profiles | |
| `category_top` | top 15 by LT score in matching categories | `category=growth` |
| `ticker_history` | one fund's scores and ranks in every kept report | `ticker=VOO` |
| `steady_yearly` | funds positive in each of the last 5 calendar years | |
| `momentum_top` / `momentum_bottom` | 50 strongest / weakest over both 1 week and 1 month | |
| `zscore_matrix` | Core / Momentum / Value-dip funds from the 1Y and 3Y Z-scores | |
| `beat_trail` | funds that beat the best index far more often than they trailed the worst, with their yearly 10% bands and a swing count | optional: `min_diff=20 min_years=5` |

**Adding your own:** type the SQL at the prompt, then `.save NAME`. Or create
`queries/NAME.sql` by hand with a `-- description` first line. Use `{name}` for a
value you must pass in when running it (`name=value`), or `{name=default}` for an
optional one (`beat_trail` uses `{min_diff=20}`); quotes inside values are handled.

Running a saved query by name (`beat_trail`, `.run beat_trail`) is easiest. You can
also paste a saved query's SQL at the prompt or on the command line: `{name=default}`
values are filled with their defaults, but a required `{name}` (like `{ticker}`)
must be replaced with a value by hand. Running the `.sql` file directly from PyCharm
or another SQL tool won't work: the tables only exist inside `query.py`, and the
`{...}` placeholders aren't SQL.

## 6. When the data changes

There is no database to update. Every run of `query.py` reads the current files:

- After `run_ci.py` or `main.py`, `report` is the new report and `reports` includes it.
- New or edited eTrade files in `etf_screener/data/` show up in `etrade`.
- `output/query_cache/` holds fast copies and is refreshed automatically when a
  source file changes. It is safe to delete; it is rebuilt on the next query.
