"""Ask questions of the screener's data with SQL -- no importing needed.

DuckDB runs SQL directly on the spreadsheets and CSVs, so new columns in a
new eTrade export or report show up automatically. Each data set is a
table name you can use in a query:

    report            newest results_profile_*.xlsx (overview tab)
    report_no_yahoo   the same report's "No Yahoo Data" tab
    etrade            all eTrade / Morningstar exports in data/, every column
    yearly_returns    calendar-year returns: ticker, year, total_return
    volatile_returns  returns in each crash / recovery period: ticker, period, total_return
    reports           overview tab of EVERY report in output/etf_screener/, with
                      run_time and source_file columns (history for as long as
                      you keep the reports)

Spreadsheets are cached as Parquet in output/query_cache/ the first time
(the eTrade files take ~30 s); a cache is rebuilt when its file changes.

Usage (from etf_screener/):
    python db_access/query.py                     # interactive prompt; type .help
    python db_access/query.py top_both            # run db_access/queries/top_both.sql
    python db_access/query.py ticker_history ticker=VOO
    python db_access/query.py "SELECT * FROM report LIMIT 5"
    python db_access/query.py --find sharpe       # which columns mention "sharpe"?
    python db_access/query.py --columns report    # every column of a table
    add --xlsx [file] to any query to save the result to Excel

Column names with spaces or brackets need double quotes:
    SELECT Ticker, "Profile LT Score" FROM report WHERE "Total Return (1Y)" > 10
"""
import argparse
import contextlib
import io
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
SCREENER = HERE.parent
sys.path.insert(0, str(SCREENER))
from config import YEARLY_RETURNS_CSV, VOLATILE_RETURNS_CSV  # noqa: E402
from data_loading import clean_dtypes, read_and_concat_excels, resolve_files_in_path  # noqa: E402

PROJECT = SCREENER.parent
REPORT_DIR = PROJECT / "output" / "etf_screener"
DATA_DIR = SCREENER / "data"
CACHE_DIR = PROJECT / "output" / "query_cache"
RESULT_DIR = PROJECT / "output" / "queries"
QUERY_DIR = HERE / "queries"
SHOW_ROWS = 50


# ---------------------------------------------------------------------------
# Data sets: each builds a DataFrame from its source files
# ---------------------------------------------------------------------------
def all_reports() -> list:
    reports = [p for p in REPORT_DIR.glob("results_profile_*.xlsx") if not p.name.startswith("~$")]
    if not reports:
        raise FileNotFoundError(f"No results_profile_*.xlsx in {REPORT_DIR} - run the screener first.")
    return sorted(reports, key=lambda p: p.stat().st_mtime)


def newest_report() -> Path:
    return all_reports()[-1]


def load_all_reports() -> pd.DataFrame:
    frames = []
    for path in all_reports():
        df = pd.read_excel(path, sheet_name=0)
        stamp = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})", path.name)
        run_time = pd.Timestamp(f"{stamp.group(1)} {stamp.group(2)}:{stamp.group(3)}:{stamp.group(4)}") if stamp else pd.NaT
        info = pd.DataFrame({"run_time": run_time, "source_file": path.name}, index=df.index)
        frames.append(pd.concat([info, df], axis=1))
    return pd.concat(frames, ignore_index=True)


def etrade_files() -> list:
    with contextlib.redirect_stdout(io.StringIO()):  # it prints every file name
        return [Path(f) for f in resolve_files_in_path(str(DATA_DIR) + "/", str(DATA_DIR) + "/")]


def load_report_tab(tab: str):
    def load():
        path = newest_report()
        sheets = pd.ExcelFile(path).sheet_names
        name = sheets[0] if tab == "overview" else tab
        if name not in sheets:
            return pd.DataFrame({"Ticker": []})
        return pd.read_excel(path, sheet_name=name)
    return load


def load_etrade() -> pd.DataFrame:
    df = read_and_concat_excels([str(f) for f in etrade_files()], usecols=None)
    return clean_dtypes(df.loc[:, ~df.columns.duplicated()])


def load_yearly() -> pd.DataFrame:
    wide = pd.read_csv(YEARLY_RETURNS_CSV, index_col=0)
    long = wide.rename_axis("ticker").reset_index().melt("ticker", var_name="year", value_name="total_return")
    long["year"] = long["year"].astype(int)
    return long.dropna(subset=["total_return"])


def load_volatile() -> pd.DataFrame:
    wide = pd.read_csv(VOLATILE_RETURNS_CSV, index_col=0)
    long = wide.rename_axis("ticker").reset_index().melt("ticker", var_name="period", value_name="total_return")
    return long.dropna(subset=["total_return"])


# name -> (source files to watch for changes, loader, description)
DATASETS = {
    "report": (lambda: [newest_report()], load_report_tab("overview"), "newest screener report (overview tab)"),
    "report_no_yahoo": (lambda: [newest_report()], load_report_tab("No Yahoo Data"), "newest report's No Yahoo Data tab"),
    "reports": (all_reports, load_all_reports, "every saved report's overview tab (run_time, source_file, ...)"),
    "etrade": (etrade_files, load_etrade, "all eTrade / Morningstar exports in data/"),
    "yearly_returns": (lambda: [Path(YEARLY_RETURNS_CSV)], load_yearly, "calendar-year returns (ticker, year, total_return)"),
    "volatile_returns": (lambda: [Path(VOLATILE_RETURNS_CSV)], load_volatile, "crash / recovery period returns (ticker, period, total_return)"),
}


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------
class Session:
    def __init__(self):
        self.con = duckdb.connect()
        self.loaded = set()
        self.last_sql = None
        self.last_result = None

    def load(self, name: str) -> None:
        """Make `name` queryable, from its Parquet cache when that's up to date."""
        if name in self.loaded:
            return
        sources, loader, _ = DATASETS[name]
        files = sources()
        if not files:
            raise FileNotFoundError(f"No source file for {name}")
        cache = CACHE_DIR / f"{name}.parquet"
        stamp = CACHE_DIR / f"{name}.source"
        source_key = "\n".join(f"{f}|{f.stat().st_mtime}" for f in files)
        if not (cache.exists() and stamp.exists() and stamp.read_text() == source_key):
            print(f"  Reading {name} ({len(files)} file(s))...", flush=True)
            started = time.time()
            df = loader()
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            self.con.register("_new", df)
            self.con.execute(f"COPY _new TO '{cache}' (FORMAT parquet)").fetchall()
            self.con.unregister("_new")
            stamp.write_text(source_key)
            print(f"  Cached {name}: {len(df)} rows, {len(df.columns)} columns ({time.time() - started:.0f} s)")
        self.con.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM '{cache}'").fetchall()
        self.loaded.add(name)

    def load_used(self, sql: str) -> None:
        """Load only the data sets the query mentions."""
        for name in DATASETS:
            if re.search(rf"\b{name}\b", sql, re.IGNORECASE):
                self.load(name)

    def run(self, sql: str) -> pd.DataFrame:
        self.load_used(sql)
        df = self.con.execute(sql).df()
        self.last_sql, self.last_result = sql, df
        return df

    def tables(self) -> pd.DataFrame:
        rows = []
        for name, (_, _, about) in DATASETS.items():
            try:
                self.load(name)
            except FileNotFoundError:
                continue
            n_rows, n_cols = self.con.execute(
                f"SELECT (SELECT count(*) FROM {name}), (SELECT count(*) FROM (DESCRIBE {name}))").fetchall()[0]
            rows.append((name, n_rows, n_cols, about))
        return pd.DataFrame(rows, columns=["table", "rows", "columns", "what"])

    def columns(self, table: str, text: str = "") -> pd.DataFrame:
        if table not in DATASETS:
            raise ValueError(f"Unknown table {table!r}; tables: {', '.join(DATASETS)}")
        self.load(table)
        ref = table
        cols = self.con.execute(f"DESCRIBE {ref}").df()[["column_name", "column_type"]]
        if text:
            cols = cols[cols["column_name"].str.contains(text, case=False, regex=False)]
        sample = self.con.execute(f"SELECT * FROM {ref} LIMIT 1000").df()
        cols.insert(0, "table", table)
        cols["use in SQL as"] = cols["column_name"].map(quote)
        cols["example value"] = cols["column_name"].map(lambda c: next(iter(sample[c].dropna()), None))
        return cols.reset_index(drop=True)

    def find(self, text: str) -> pd.DataFrame:
        found = []
        for name in DATASETS:
            try:
                found.append(self.columns(name, text))
            except FileNotFoundError:
                continue
        found = [f for f in found if len(f)]
        return pd.concat(found, ignore_index=True) if found else pd.DataFrame()


def quote(column: str) -> str:
    return column if re.fullmatch(r"[a-z_][a-z0-9_]*", column) else '"' + column.replace('"', '""') + '"'


# ---------------------------------------------------------------------------
# Saved queries (db_access/queries/*.sql)
# ---------------------------------------------------------------------------
def saved_queries() -> dict:
    return {p.stem: p for p in sorted(QUERY_DIR.glob("*.sql"))}


def describe_query(path: Path) -> str:
    first = path.read_text().splitlines()[0] if path.read_text() else ""
    return first.lstrip("- ").strip()


PARAMETER = re.compile(r"\{(\w+)(?:=([^}]*))?\}")  # {name} or {name=default}


def fill_parameters(sql: str, params: list) -> str:
    """Replace {name} / {name=default} in a saved query with name=value arguments."""
    values = dict(p.split("=", 1) for p in params if "=" in p)
    missing = sorted({m.group(1) for m in PARAMETER.finditer(sql) if m.group(2) is None} - set(values))
    if missing:
        raise ValueError(f"This query needs: {', '.join(f'{m}=...' for m in missing)} "
                         f"(run it by name with those values, e.g. .run NAME {missing[0]}=..., "
                         f"or replace {{{missing[0]}}} in the SQL with a value)")
    return PARAMETER.sub(lambda m: values.get(m.group(1), m.group(2)).replace("'", "''"), sql)


def query_text(name_or_sql: str, params: list) -> tuple:
    """(label, sql) for a saved query name or a literal SQL statement."""
    queries = saved_queries()
    if name_or_sql in queries:
        return name_or_sql, fill_parameters(queries[name_or_sql].read_text(), params)
    return "query", fill_parameters(name_or_sql, params)  # pasted saved-query text works too


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def show(df: pd.DataFrame, limit: int = SHOW_ROWS) -> None:
    if df is None or df.empty:
        print("(no rows)")
        return
    with pd.option_context("display.max_columns", 30, "display.width", 250, "display.max_colwidth", 45):
        print((df if limit is None else df.head(limit)).to_string(index=False))
    more = f" (showing first {limit}; use .xlsx to save all)" if limit and len(df) > limit else ""
    print(f"\n{len(df)} row(s){more}")


def save_xlsx(df: pd.DataFrame, label: str, path: str = None) -> Path:
    out = Path(path) if path else RESULT_DIR / f"{label}_{datetime.now():%Y-%m-%d_%H-%M-%S}.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(out, index=False)
    print(f"Saved {len(df)} row(s) to {out}")
    return out


# ---------------------------------------------------------------------------
# Interactive prompt
# ---------------------------------------------------------------------------
HELP = """Type SQL ending with ; (it can span several lines), or a command:
  .tables                  list the data sets with row and column counts
  .columns TABLE [text]    columns of a table, optionally only those containing text
  .find TEXT               columns in any data set whose name contains TEXT
  .queries                 list saved queries (db_access/queries/*.sql)
  .run NAME [k=v ...]      run a saved query, e.g. .run ticker_history ticker=VOO
  .save NAME               save the last SQL as db_access/queries/NAME.sql
  .xlsx [file]             save the last result to Excel (default output/queries/)
  .help                    this list
  .quit                    leave
Example:  SELECT Ticker, Name, "Profile LT Score" FROM report ORDER BY 3 DESC LIMIT 10;"""


def interactive(session: Session) -> None:
    print("ETF screener SQL prompt. Type .help for commands, .tables to see the data.")
    label, buffer = "query", []
    while True:
        try:
            line = input("sql> " if not buffer else "...> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return
        stripped = line.strip()
        if not buffer and stripped.startswith("."):
            command, *args = stripped.split()
            try:
                if command in (".quit", ".exit", ".q"):
                    return
                elif command == ".help":
                    print(HELP)
                elif command == ".tables":
                    show(session.tables(), limit=None)
                elif command == ".columns" and args:
                    show(session.columns(args[0], " ".join(args[1:])), limit=None)
                elif command == ".find" and args:
                    show(session.find(" ".join(args)), limit=None)
                elif command == ".queries":
                    for name, path in saved_queries().items():
                        print(f"  {name:22} {describe_query(path)}")
                elif command == ".run" and args:
                    label, sql = query_text(args[0], args[1:])
                    show(session.run(sql))
                elif command == ".save" and args and session.last_sql:
                    QUERY_DIR.mkdir(exist_ok=True)
                    (QUERY_DIR / f"{args[0]}.sql").write_text(session.last_sql.strip() + "\n")
                    print(f"Saved as {QUERY_DIR / args[0]}.sql")
                elif command == ".xlsx" and session.last_result is not None:
                    save_xlsx(session.last_result, label, args[0] if args else None)
                else:
                    print("Unknown command or missing argument; type .help")
            except Exception as exc:  # noqa: BLE001 - show the error and keep the prompt
                print(f"Error: {exc}")
            continue
        if not stripped and not buffer:
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            sql, buffer, label = "\n".join(buffer), [], "query"
            try:
                show(session.run(fill_parameters(sql, [])))  # {name=default} -> default
            except Exception as exc:  # noqa: BLE001
                print(f"Error: {exc}")
                hint_columns(session, str(exc))


def hint_columns(session: Session, error: str) -> None:
    """On an unknown-column error, suggest real column names."""
    match = re.search(r'column with name "?([^"\s]+)"? does not exist|Referenced column "([^"]+)" not found', error)
    if match:
        word = (match.group(1) or match.group(2)).split()[0][:6]
        similar = session.find(word)
        if len(similar):
            print("Columns with a similar name:")
            show(similar[["table", "use in SQL as"]].head(15))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("query", nargs="?", help="saved query name or SQL statement; none = interactive")
    parser.add_argument("params", nargs="*", help="name=value for {name} in a saved query")
    parser.add_argument("--xlsx", nargs="?", const="", help="save the result to Excel")
    parser.add_argument("--find", metavar="TEXT", help="list columns whose name contains TEXT")
    parser.add_argument("--columns", metavar="TABLE", help="list a table's columns")
    parser.add_argument("--tables", action="store_true", help="list the data sets")
    args = parser.parse_args()

    session = Session()
    if args.tables:
        show(session.tables(), limit=None)
    elif args.find:
        show(session.find(args.find), limit=None)
    elif args.columns:
        show(session.columns(args.columns), limit=None)
    elif args.query:
        label, sql = query_text(args.query, args.params)
        df = session.run(sql)
        show(df)
        if args.xlsx is not None:
            save_xlsx(df, label, args.xlsx or None)
    else:
        interactive(session)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, FileNotFoundError, duckdb.Error) as exc:
        sys.exit(f"Error: {exc}")
