"""
E*TRADE ETF / Mutual Fund merger

Reads the E*TRADE screener exports in eTrade/source-files (ETFs-Export.xlsx, Funds.xlsx),
merges every tab of each file on Symbol, stacks ETFs and funds into one table, and drops:
  - money market funds/ETFs (Fund Category contains "Money Market")
  - funds with less than one year of history
      (inception date taken from "Inception date" or the "(MM/DD/YYYY)" suffix of
       "Since Inception Return"; when no inception date is known, a missing
       1 Year Return is treated as < 1 year of history)
  - funds whose Since Inception Return is below 0

Output (output/etrade):
  - etrade-merged.xlsx               all kept rows, one sheet
  - etrade-merged_ticker_N.csv       250 symbols per file, " ,Quantity,Cost Basis" format
                                     (for uploading as a Morningstar portfolio)

Usage:
  python eTrade/merge-etrade-etf-fund.py [--no-prices]
    --no-prices   skip the Yahoo price lookup for mutual funds (Cost Basis = 1.0)
"""

import argparse
import re
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

SOURCE_DIR = Path(__file__).parent / "source-files"
OUTPUT_DIR = Path(__file__).parent.parent / "output" / "etrade"
OUTPUT_STEM = "etrade-merged"
CHUNK_SIZE = 250
YAHOO_BATCH_SIZE = 200
YAHOO_PAUSE_SECONDS = 5
YAHOO_RETRIES = 3

SINCE_INCEPTION = "Since Inception Return"
ONE_YEAR = "1 Year Return"
INCEPTION_DATE = "Inception Date"

INCEPTION_IN_RETURN = re.compile(r"\((\d{1,2}/\d{1,2}/\d{4})\)\s*$")
NUMBER = re.compile(r"^[+-]?\$?[\d,]*\.?\d+\s*([%BMKTx]|yrs)?$")
MULTIPLIER = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}


def pick_source_files(source_dir: Path) -> list[Path]:
    """One file per stem; when both Funds.xls and Funds.xlsx exist, the newer one wins."""
    by_stem: dict[str, Path] = {}
    for f in sorted(source_dir.glob("*.xls*")):
        if f.name.startswith("~$") or f.suffix.lower() not in {".xls", ".xlsx"}:
            continue
        current = by_stem.get(f.stem)
        if current is None or f.stat().st_mtime > current.stat().st_mtime:
            if current is not None:
                print(f"  Skipping older {current.name} (using {f.name})")
            by_stem[f.stem] = f
        else:
            print(f"  Skipping older {f.name} (using {current.name})")
    if not by_stem:
        raise FileNotFoundError(f"No Excel files found in {source_dir}")
    return list(by_stem.values())


def canonical(col: str, known: dict[str, str]) -> str:
    """Unify column spellings across files (case-insensitive), e.g. 'Fund category' -> 'Fund Category'."""
    col = col.strip()
    if col in {"ETF Name", "Fund name", "Fund Name"}:
        return "Name"
    return known.setdefault(col.lower(), col)


def read_workbook(path: Path, known_cols: dict[str, str]) -> pd.DataFrame:
    """Merge all tabs of one export on Symbol."""
    merged = None
    for sheet, df in pd.read_excel(path, sheet_name=None, dtype=str).items():
        if "Symbol" not in df.columns:
            print(f"  Skipping tab '{sheet}' (no Symbol column)")
            continue
        df = df.rename(columns=lambda c: canonical(c, known_cols))
        df = df.loc[:, ~df.columns.duplicated()]
        df["Symbol"] = df["Symbol"].str.strip()
        df = df.dropna(subset=["Symbol"]).drop_duplicates("Symbol").set_index("Symbol")
        if merged is None:
            merged = df
        else:
            merged = merged.join(df[[c for c in df.columns if c not in merged.columns]], how="outer")
    if merged is None:
        raise ValueError(f"{path.name}: no tabs with a Symbol column")
    print(f"  {path.name}: {len(merged)} symbols, {len(merged.columns)} columns")
    return merged


def to_number(value):
    """'+4.07%' -> 0.0407, '$4.56B' -> 4.56e9, '11.72 yrs' -> 11.72, '20.13x' -> 20.13."""
    if pd.isna(value):
        return pd.NA
    s = str(value).strip()
    m = NUMBER.match(s)
    if not m:
        return pd.NA
    num = float(re.sub(r"[^\d.+-]", "", s.replace("yrs", "")))
    suffix = m.group(1)
    if suffix == "%":
        return round(num / 100, 6)
    return num * MULTIPLIER.get(suffix, 1)


def convert_types(df: pd.DataFrame) -> tuple[pd.DataFrame, set[str]]:
    """Convert numeric-looking text columns; returns the set of percent columns for formatting."""
    df = df.replace({"--": pd.NA, "": pd.NA})

    if SINCE_INCEPTION in df.columns:
        from_return = df[SINCE_INCEPTION].str.extract(INCEPTION_IN_RETURN, expand=False)
        existing = df[INCEPTION_DATE] if INCEPTION_DATE in df.columns else pd.Series(pd.NA, index=df.index)
        df[INCEPTION_DATE] = pd.to_datetime(existing.fillna(from_return), format="%m/%d/%Y", errors="coerce")
        df[SINCE_INCEPTION] = df[SINCE_INCEPTION].str.replace(INCEPTION_IN_RETURN, "", regex=True)

    percent_cols = set()
    for col in df.columns:
        if col in {"Name", "Type", INCEPTION_DATE}:
            continue
        values = df[col].dropna().astype(str).str.strip()
        if values.empty or not values.str.match(NUMBER).all():
            continue
        if values.str.endswith("%").any():
            percent_cols.add(col)
        df[col] = pd.to_numeric(df[col].map(to_number), errors="coerce")
    return df, percent_cols


def filter_funds(df: pd.DataFrame) -> pd.DataFrame:
    one_year_ago = pd.Timestamp(date.today() - timedelta(days=365))
    inception = df[INCEPTION_DATE]
    short_history = (inception > one_year_ago) | (inception.isna() & df[ONE_YEAR].isna())
    negative_return = df[SINCE_INCEPTION] < 0
    money_market = df["Fund Category"].str.contains("Money Market", case=False, na=False)

    dropped = pd.Series(False, index=df.index)
    for label, mask in [("money market", money_market),
                        ("< 1 year of history", short_history),
                        ("Since Inception Return < 0", negative_return)]:
        print(f"  Dropping {(mask & ~dropped).sum()} for {label}")
        dropped |= mask
    return df[~dropped]


def download_closes(symbols: list[str]) -> dict[str, float]:
    """Latest close per symbol. Fetches the last 5 days, not 1, so a weekend, holiday or a
    fund's NAV not being posted yet for today still yields the most recent close.

    yf.download doesn't raise on rate limits; it records them in yf_shared._ERRORS, so the
    rate-limited symbols are retried with an increasing wait."""
    import yfinance as yf
    import yfinance.shared as yf_shared

    prices: dict[str, float] = {}
    todo = symbols
    for attempt in range(YAHOO_RETRIES + 1):
        data = yf.download(todo, period="5d", progress=False, auto_adjust=False)
        if not data.empty:
            closes = data["Close"].ffill().iloc[-1]
            prices.update({s: round(float(p), 2) for s, p in closes.items() if pd.notna(p)})
        todo = [s for s, err in yf_shared._ERRORS.items() if "RateLimit" in str(err) and s not in prices]
        if not todo or attempt == YAHOO_RETRIES:
            break
        wait = YAHOO_PAUSE_SECONDS * 6 * 2 ** attempt
        print(f"    Rate limited on {len(todo)} symbols; waiting {wait}s before retry")
        time.sleep(wait)
    return prices


def fetch_prices(symbols: list[str]) -> dict[str, float]:
    """Last close from Yahoo, in small batches with a pause between them to avoid rate limits."""
    prices: dict[str, float] = {}
    for i in range(0, len(symbols), YAHOO_BATCH_SIZE):
        batch = symbols[i:i + YAHOO_BATCH_SIZE]
        print(f"  Yahoo prices {i + 1}-{i + len(batch)} of {len(symbols)}...")
        prices.update(download_closes(batch))
        time.sleep(YAHOO_PAUSE_SECONDS)
    print(f"  Got Yahoo prices for {len(prices)}/{len(symbols)} symbols")
    return prices


def cost_basis(df: pd.DataFrame, use_yahoo: bool) -> pd.Series:
    basis = df["Market Price"] if "Market Price" in df.columns else pd.Series(pd.NA, index=df.index)
    missing = basis.index[basis.isna()].tolist()
    counts = df.loc[missing, "Type"].value_counts().to_dict()
    print(f"Cost Basis: {len(df) - len(missing)} from E*TRADE Market Price; "
          f"{len(missing)} without one {counts} -> Yahoo")
    if use_yahoo and missing:
        basis = basis.fillna(pd.Series(fetch_prices(missing), dtype=float))
    print(f"Cost Basis: {basis.isna().sum()} with no price anywhere -> set to 1")
    return basis.fillna(1.0).round(2)


def write_ticker_files(df: pd.DataFrame, basis: pd.Series) -> list[Path]:
    for old in OUTPUT_DIR.glob(f"{OUTPUT_STEM}_ticker_*.csv"):
        old.unlink()
    paths = []
    symbols = df.index.tolist()
    for n, i in enumerate(range(0, len(symbols), CHUNK_SIZE), start=1):
        path = OUTPUT_DIR / f"{OUTPUT_STEM}_ticker_{n}.csv"
        with open(path, "w") as f:
            f.write(" ,Quantity,Cost Basis\n")
            for symbol in symbols[i:i + CHUNK_SIZE]:
                f.write(f"{symbol},1,{basis[symbol]}\n")
        paths.append(path)
    return paths


def write_excel(df: pd.DataFrame, percent_cols: set[str], path: Path) -> None:
    with pd.ExcelWriter(path, engine="xlsxwriter", datetime_format="yyyy-mm-dd") as writer:
        df.to_excel(writer, sheet_name="Merged")
        book, sheet = writer.book, writer.sheets["Merged"]
        pct = book.add_format({"num_format": "0.00%"})
        num = book.add_format({"num_format": "#,##0.##"})
        for idx, col in enumerate(["Symbol", *df.columns]):
            if col == "Name":
                sheet.set_column(idx, idx, 40)
            elif col in percent_cols:
                sheet.set_column(idx, idx, 14, pct)
            elif col != "Symbol" and pd.api.types.is_numeric_dtype(df[col]):
                sheet.set_column(idx, idx, 14, num)
            else:
                sheet.set_column(idx, idx, 14)
        sheet.freeze_panes(1, 2)
        sheet.autofilter(0, 0, len(df), len(df.columns))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-prices", action="store_true", help="skip Yahoo price lookup for mutual funds")
    args = parser.parse_args()

    print(f"Reading {SOURCE_DIR}")
    known_cols = {c.lower(): c for c in (SINCE_INCEPTION, ONE_YEAR, INCEPTION_DATE)}
    frames = []
    for path in pick_source_files(SOURCE_DIR):
        df = read_workbook(path, known_cols)
        df.insert(1, "Type", "ETF" if "ETF" in path.name.upper() else "Mutual Fund")
        frames.append(df)

    merged = pd.concat(frames)
    merged = merged[~merged.index.duplicated()]
    merged, percent_cols = convert_types(merged)
    print(f"Merged {len(merged)} symbols")

    merged = filter_funds(merged)
    print(f"Kept {len(merged)} symbols ({merged['Type'].value_counts().to_dict()})")

    front = ["Name", "Type", INCEPTION_DATE, SINCE_INCEPTION, ONE_YEAR]
    merged = merged[front + [c for c in merged.columns if c not in front]].sort_index()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    excel_path = OUTPUT_DIR / f"{OUTPUT_STEM}.xlsx"
    write_excel(merged, percent_cols, excel_path)
    print(f"Created {excel_path}")

    paths = write_ticker_files(merged, cost_basis(merged, use_yahoo=not args.no_prices))
    print(f"Created {len(paths)} ticker CSVs: {paths[0].name} ... {paths[-1].name}")


if __name__ == "__main__":
    main()
