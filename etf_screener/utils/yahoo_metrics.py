"""Consolidated, reusable Yahoo Finance metrics for the ETF screener.

This module is the single source of truth for everything derived from
Yahoo Finance: sub-sector classification (via top-holdings look-through),
Sharpe Ratio (1Y/3Y), and sector-relative Z-Scores. The command-line
wrapper standalone_utils/get_yahoo_dta.py calls get_yahoo_metrics_for_tickers()
for an ad hoc watchlist.

Design goals:
  - Callable two ways: pass a list of tickers directly (main.py's CI
    flow, using tickers already present in the merged Morningstar
    dataframe), or read tickers from a tickers.txt-style file (standalone
    local runs via standalone_utils/get_yahoo_dta.py, useful for testing against an
    arbitrary watchlist independent of the spreadsheet universe).
  - Every per-ticker Yahoo Finance call is wrapped so a single bad/
    delisted/rate-limited ticker never aborts the whole batch -- failures
    are logged and the ticker gets safe NaN/default placeholders instead.
  - All tunables (batch size, rest delay, retries, sample size) are the
    YahooMetricsConfig defaults below; a profile YAML can override any of
    them in an optional thresholds.yahoo_metrics block.
"""
from __future__ import annotations

import json
import os
import random
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

from utils.yf_download import download_prices, is_rate_limit_error

# =========================================================================
# SECTOR / SUB-SECTOR TAXONOMY
# 11 core sectors, ~33 sub-sectors. Keys are matched against yfinance's
# industryKey / sectorKey fields on individual equity holdings.
# =========================================================================
SECTOR_TAXONOMY = {
    "Technology": {
        "Semiconductors & Semiconductor Equipment": ["semiconductor", "chip"],
        "Software & Services": ["software", "internet-content", "cloud", "saas"],
        "Technology Hardware, Storage & Peripherals": ["hardware", "storage", "peripheral", "consumer-electronics"],
        "IT Services & Consulting": ["information-technology-services", "it-services", "consulting"],
    },
    "Healthcare": {
        "Pharmaceuticals": ["drug-manufacturer", "pharmaceutical"],
        "Biotechnology": ["biotechnology", "biotech"],
        "Healthcare Equipment & Supplies": ["medical-devices", "medical-instruments", "diagnostics"],
        "Healthcare Providers & Services": ["healthcare-plans", "medical-care", "hospital"],
    },
    "Financials": {
        "Banks": ["bank"],
        "Financial Services": ["credit-services", "capital-markets", "asset-management", "financial-data"],
        "Insurance": ["insurance"],
    },
    "Communication Services": {
        "Interactive Media & Services": ["internet-content", "interactive-media"],
        "Entertainment & Broadcasting": ["entertainment", "broadcasting", "gaming"],
        "Diversified Telecommunication Services": ["telecom"],
    },
    "Consumer Cyclical": {
        "Automobiles & Components": ["auto-manufacturer", "auto-parts"],
        "Broadline Retail & E-Commerce": ["internet-retail", "e-commerce"],
        "Hotels, Restaurants & Leisure": ["restaurant", "lodging", "leisure", "resort"],
        "Household Durables & Apparel": ["apparel", "furnishings", "textile"],
    },
    "Consumer Staples": {
        "Beverages & Tobacco": ["beverage", "tobacco"],
        "Food & Staples Retailing": ["grocery", "food-retail", "discount-store"],
        "Household & Personal Products": ["household-products", "personal-products"],
    },
    "Energy": {
        "Oil, Gas & Consumable Fuels": ["oil-gas", "fuel"],
        "Energy Equipment & Services": ["oil-gas-equipment", "drilling"],
    },
    "Industrials": {
        "Aerospace & Defense": ["aerospace", "defense"],
        "Air Freight & Logistics / Transportation": ["airline", "trucking", "railroad", "logistics", "freight"],
        "Machinery & Electrical Equipment": ["machinery", "electrical-equipment", "farm-heavy-machinery"],
    },
    "Materials": {
        "Chemicals": ["chemical"],
        "Metals & Mining": ["metals-mining", "gold", "copper", "steel"],
        "Containers & Packaging": ["packaging", "containers"],
    },
    "Utilities": {
        "Electric, Gas, and Water Utilities": ["utilities-regulated"],
        "Independent Power & Renewable Electricity Producers": ["utilities-renewable", "independent-power"],
    },
    "Real Estate": {
        "Equity REITs": ["reit"],
        "Real Estate Management & Development": ["real-estate-services", "real-estate-development"],
    },
}

SUBSECTOR_KEYWORDS: Dict[str, List[str]] = {
    sub_label: keywords
    for sector, subsectors in SECTOR_TAXONOMY.items()
    for sub_label, keywords in subsectors.items()
}

DEFAULT_SUBSECTOR = "Broad Market Equity"

unmapped_key_log: set = set()


@dataclass
class YahooMetricsConfig:
    """Tunables for the Yahoo fetch pipeline -- the one place their
    defaults live. Any field can be overridden in an optional
    thresholds.yahoo_metrics block of a profile YAML (e.g.
    force_refresh_subsector: true for one run).
    """
    batch_size: int = 200               # tickers per price download
    rest_delay_seconds: float = 3.0     # pause between price downloads
    rest_delay_jitter_seconds: float = 2.0
    subsector_workers: int = 4          # parallel sub-sector lookups
    sample_stock_lookups: int = 10      # Yahoo lists at most 10 top holdings
    max_download_retries: int = 3
    risk_free_annual: float = 0.04
    price_history_period: str = "3y"
    log_unmapped_keys: bool = True
    subsector_cache_path: str = "utils/sector_cache.json"
    subsector_cache_max_age_days: int = 365
    force_refresh_subsector: bool = False

    @property
    def risk_free_monthly(self) -> float:
        return self.risk_free_annual / 12

    @classmethod
    def from_thresholds(cls, thresholds: Optional[dict]) -> "YahooMetricsConfig":
        """Build a config from a profile input YAML's thresholds dict,
        e.g. thresholds["yahoo_metrics"] = {"batch_size": 25, ...}.
        Omitted keys use the dataclass defaults above; an unknown key
        (likely a typo) is an error.
        """
        overrides = (thresholds or {}).get("yahoo_metrics", {}) or {}
        unknown = sorted(set(overrides) - set(cls.__dataclass_fields__))
        if unknown:
            raise ValueError(f"Unknown thresholds.yahoo_metrics key(s) {unknown}; "
                             f"valid: {sorted(cls.__dataclass_fields__)}")
        return cls(**overrides)


# =========================================================================
# SUB-SECTOR CACHE (disk-backed, monthly by default)
# =========================================================================

def _load_subsector_cache(cache_path: str) -> Dict[str, Dict[str, str]]:
    """Load the on-disk sub-sector cache as {ticker: {sub_sector, cached_date}}.
    Returns {} if the file doesn't exist or fails to parse -- never raises.
    """
    if not os.path.exists(cache_path):
        return {}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_subsector_cache(cache_path: str, cache_data: Dict[str, Dict[str, str]]) -> None:
    """Write the sub-sector cache back to disk, creating parent dirs as needed."""
    directory = os.path.dirname(cache_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, indent=2, sort_keys=True)


def _is_cache_entry_fresh(entry: Dict[str, str], max_age_days: int, ticker: str = "") -> bool:
    """True if entry has a parseable cached_date within max_age_days of now."""
    cached_date_str = entry.get("cached_date")
    if not cached_date_str:
        return False
    try:
        cached_date = datetime.fromisoformat(cached_date_str)
    except Exception:
        return False
    # Each ticker gets 0-29 extra days (fixed per ticker), so entries cached
    # on the same day are refreshed over a month instead of all at once.
    spread = zlib.crc32(ticker.encode()) % 30 if ticker else 0
    return (datetime.now() - cached_date) <= timedelta(days=max_age_days + spread)


# =========================================================================
# TICKER INPUT HELPERS
# =========================================================================

def read_tickers_from_file(path: str) -> List[str]:
    """Read a tickers.txt-style file: comma/tab/newline separated, '#'
    comment lines ignored, deduplicated and sorted. Used only by the
    standalone CLI (standalone_utils/get_yahoo_dta.py) for ad hoc local runs -- the CI
    flow (main.py) passes tickers in directly from the merged dataframe
    instead of reading this file.
    """
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        raw_content = f.read()

    processed = []
    for line in raw_content.replace(",", "\n").replace("\t", "\n").split("\n"):
        clean = line.strip().upper()
        if clean and not clean.startswith("#"):
            processed.append(clean)
    return sorted(set(processed))


# =========================================================================
# SUB-SECTOR CLASSIFICATION
# =========================================================================

def classify_holding_subsector(ind_key: str, sec_key: str, log_unmapped: bool = True) -> str:
    """Match a stock's industryKey/sectorKey against the sub-sector
    taxonomy. Falls back to DEFAULT_SUBSECTOR if nothing matches, and
    optionally logs the unmatched pair for later taxonomy tuning.
    """
    combined = f"{ind_key} {sec_key}".lower()
    for sub_label, keywords in SUBSECTOR_KEYWORDS.items():
        if any(kw in combined for kw in keywords):
            return sub_label
    if log_unmapped and (ind_key or sec_key):
        unmapped_key_log.add((ind_key, sec_key))
    return DEFAULT_SUBSECTOR


def _is_skippable_holding_symbol(stock_symbol: str) -> bool:
    """Filter out non-equity holding symbols (futures, options, cash
    sleeves, synthetic placeholders) that can appear inside ETF
    top_holdings tables and trigger noisy Yahoo 404 lookups."""
    if not stock_symbol:
        return True
    if any(ch in stock_symbol for ch in ["=", "/", "^"]):
        return True
    if len(stock_symbol) > 5 and stock_symbol[-3:].isalnum() and any(ch.isdigit() for ch in stock_symbol[-3:]):
        return True
    if not stock_symbol.replace(".", "").replace("-", "").isalnum():
        return True
    return False


def _cache_subsector(cache: Optional[Dict[str, Dict[str, str]]], ticker: str, sub_sector: str) -> None:
    if cache is not None:
        cache[ticker] = {"sub_sector": sub_sector, "cached_date": datetime.now().isoformat()}


def resolve_ticker_subsector(
    ticker: str,
    cfg: YahooMetricsConfig,
    errors: Optional[List[str]] = None,
    subsector_cache: Optional[Dict[str, Dict[str, str]]] = None,
    holding_info_cache: Optional[Dict[str, Any]] = None,
) -> str:
    """For a single ETF ticker, look through its top holdings, classify
    each holding's industryKey/sectorKey, and return the sub-sector with
    the highest aggregated holding weight. Returns DEFAULT_SUBSECTOR on
    any missing/errored data -- never raises, so one bad ticker can't
    abort a batch. Any handled exception is appended to `errors` (if
    provided) for later diagnostic reporting.

    `subsector_cache`: disk-backed {ticker: {sub_sector, cached_date}} dict.
    If a fresh entry exists (within cfg.subsector_cache_max_age_days) and
    cfg.force_refresh_subsector is False, the Yahoo funds_data/holdings
    fetch is skipped entirely and the cached value is returned -- this is
    the expensive call, so caching it is the main speed win.

    `holding_info_cache`: in-memory {stock_symbol: info_dict} reused across
    ALL tickers within a single run, so a holding shared by multiple ETFs
    (e.g. AAPL, MSFT) only triggers one yf.Ticker(...).info call all run.
    """
    if subsector_cache is not None and not cfg.force_refresh_subsector:
        cached_entry = subsector_cache.get(ticker)
        if cached_entry and _is_cache_entry_fresh(cached_entry, cfg.subsector_cache_max_age_days, ticker):
            return cached_entry.get("sub_sector", DEFAULT_SUBSECTOR)

    try:
        t_obj = yf.Ticker(ticker)
        f_data = t_obj.funds_data
        holdings_df = f_data.top_holdings if f_data is not None else None
    except Exception as exc:
        if errors is not None:
            errors.append(f"{ticker}: failed to fetch funds_data ({exc})")
        # "No Fund data found" is Yahoo's real answer, so cache it like an
        # empty holdings list; network / rate-limit errors are retried next run
        if "No Fund data found" in str(exc):
            _cache_subsector(subsector_cache, ticker, DEFAULT_SUBSECTOR)
        return DEFAULT_SUBSECTOR

    if holdings_df is None or holdings_df.empty:
        if errors is not None:
            errors.append(f"{ticker}: no top_holdings data available (non-ETF or unsupported by Yahoo)")
        # cached too, so funds without holdings data (most bond / mutual
        # funds) aren't looked up again every run
        _cache_subsector(subsector_cache, ticker, DEFAULT_SUBSECTOR)
        return DEFAULT_SUBSECTOR

    weight_matrix: Dict[str, float] = {}
    top_stocks = holdings_df.index.tolist()
    loop_limit = min(len(top_stocks), cfg.sample_stock_lookups)
    info_cache: Dict[str, Any] = holding_info_cache if holding_info_cache is not None else {}
    rate_limited = False

    for stock_symbol in top_stocks[:loop_limit]:
        try:
            stock_symbol = str(stock_symbol).strip().upper()
            if _is_skippable_holding_symbol(stock_symbol):
                continue

            if stock_symbol in info_cache:
                s_info = info_cache[stock_symbol]
            else:
                s_info = yf.Ticker(stock_symbol).info
                info_cache[stock_symbol] = s_info
            if not s_info:
                continue
            ind_key = str(s_info.get("industryKey", "")).lower() if s_info.get("industryKey", "") else ""
            sec_key = str(s_info.get("sectorKey", "")).lower() if s_info.get("sectorKey", "") else ""

            raw_weight = holdings_df.loc[stock_symbol].get("Holding Percent", 0.0)
            holding_weight = float(raw_weight) if raw_weight is not None else 0.0

            sub_sector = classify_holding_subsector(ind_key, sec_key, log_unmapped=cfg.log_unmapped_keys)
            weight_matrix[sub_sector] = weight_matrix.get(sub_sector, 0.0) + holding_weight
        except Exception as exc:
            rate_limited = rate_limited or is_rate_limit_error(repr(exc))
            continue

    resolved_sub_sector = DEFAULT_SUBSECTOR
    if weight_matrix:
        max_sub_sector = max(weight_matrix, key=weight_matrix.get)
        if weight_matrix[max_sub_sector] > 0:
            resolved_sub_sector = max_sub_sector

    if rate_limited and errors is not None:
        errors.append(f"{ticker}: Yahoo rate limit during holdings lookup -- sub-sector not cached, retried next run")
    if not rate_limited:
        _cache_subsector(subsector_cache, ticker, resolved_sub_sector)

    return resolved_sub_sector


# =========================================================================
# SHARPE RATIO (via batched price history)
# =========================================================================

def _download_price_history(
    tickers: List[str],
    cfg: YahooMetricsConfig,
    errors: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Adjusted-close daily prices (tickers as columns) for a batch,
    retrying tickers Yahoo rate-limits. Never raises: tickers that still
    fail are logged and get NaN Sharpe values.
    """
    prices, failed = download_prices(
        tickers, "Adj Close", retries=cfg.max_download_retries,
        period=cfg.price_history_period, interval="1d", auto_adjust=False,
    )
    if errors is not None:
        for t in failed:
            errors.append(f"{t}: price download failed (Yahoo rate limit) -- Sharpe left as NaN.")
    return prices


def _compute_sharpe_for_batch(
    daily_prices: pd.DataFrame,
    tickers: List[str],
    cfg: YahooMetricsConfig,
    errors: Optional[List[str]] = None,
) -> Dict[str, Dict[str, float]]:
    """Compute Sharpe_1Y / Sharpe_3Y for each ticker in `tickers` from a
    downloaded price-history batch. Missing/insufficient data for a
    given ticker yields NaN for that ticker only (logged to `errors`),
    never raises.
    """
    results: Dict[str, Dict[str, float]] = {
        t: {"Sharpe_1Y": np.nan, "Sharpe_3Y": np.nan} for t in tickers
    }

    if daily_prices.empty:
        if errors is not None:
            errors.append("Batch price data empty -- Sharpe left as NaN for this batch.")
        return results

    monthly_prices = daily_prices.resample("ME").last()
    # Returns per fund: a batch-wide dropna() would cut every fund's history
    # to the shortest one in the batch (one new or delisted fund could leave
    # the whole batch with a few months, or none)
    all_monthly_returns = monthly_prices.pct_change(fill_method=None)
    last_12_months = all_monthly_returns.index[-12:]
    rf_monthly = cfg.risk_free_monthly

    def _sharpe(returns: pd.Series, min_months: int) -> float:
        returns = returns.dropna()
        if len(returns) < min_months:
            return np.nan  # too little history (e.g. a fund launched recently)
        excess = returns - rf_monthly
        std = excess.std()
        return (excess.mean() / std) * np.sqrt(12) if (std > 0 and not pd.isna(std)) else np.nan

    for ticker in tickers:
        if ticker not in all_monthly_returns.columns or all_monthly_returns[ticker].isna().all():
            if errors is not None:
                errors.append(f"{ticker}: no price series returned by Yahoo -- Sharpe left as NaN.")
            continue
        try:
            series = all_monthly_returns[ticker]
            results[ticker] = {
                "Sharpe_1Y": _sharpe(series.loc[last_12_months], min_months=11),
                "Sharpe_3Y": _sharpe(series, min_months=30),
            }
        except Exception as exc:
            if errors is not None:
                errors.append(f"{ticker}: Sharpe calculation failed ({exc}) -- left as NaN.")

    return results


# =========================================================================
# MAIN ENTRY POINT
# =========================================================================

def add_subsector_z_scores(df_matrix: pd.DataFrame) -> pd.DataFrame:
    """(Re)compute Z_Score_1Y / Z_Score_3Y: each fund's Sharpe compared with
    the other funds in the frame that share its Yahoo_SubSector. Call it on
    exactly the funds that should be peers -- e.g. after narrowing an
    earlier download to one profile's eligible funds."""
    df_matrix = df_matrix.copy()
    try:
        df_matrix["Z_Score_1Y"] = df_matrix.groupby("Yahoo_SubSector")["Sharpe_1Y"].transform(
            lambda x: (x - x.mean()) / x.std() if (x.std() > 0 and not pd.isna(x.std())) else 0.0
        )
        df_matrix["Z_Score_3Y"] = df_matrix.groupby("Yahoo_SubSector")["Sharpe_3Y"].transform(
            lambda x: (x - x.mean()) / x.std() if (x.std() > 0 and not pd.isna(x.std())) else 0.0
        )
    except Exception as z_error:
        print(f"  [Yahoo Metrics] [Warning] Z-score calculation failed: {z_error}")
        df_matrix["Z_Score_1Y"] = 0.0
        df_matrix["Z_Score_3Y"] = 0.0
    return df_matrix


def get_yahoo_metrics_for_tickers(
    tickers: Iterable[str],
    cfg: Optional[YahooMetricsConfig] = None,
) -> pd.DataFrame:
    """Resolve Yahoo_SubSector, Sharpe_1Y, Sharpe_3Y, Z_Score_1Y, and
    Z_Score_3Y for each unique ticker in `tickers`.

    Returns a DataFrame with one row per unique ticker:
      ['Ticker', 'Yahoo_SubSector', 'Sharpe_1Y', 'Sharpe_3Y',
       'Z_Score_1Y', 'Z_Score_3Y', 'Yahoo_Fetch_Error']

    'Yahoo_Fetch_Error' is blank for tickers that resolved cleanly, or a
    short diagnostic string for tickers where sub-sector/Sharpe data was
    unavailable/failed (kept in the frame instead of raised, so a few
    bad tickers never abort the batch or the wider screener run).

    Z-scores are computed once at the end across the FULL set of
    `tickers` passed in -- grouped by Yahoo_SubSector -- so the peer
    group is exactly whatever universe the caller provides (the merged
    Morningstar spreadsheet's tickers, in the CI flow; or tickers.txt's
    list, in standalone local runs).
    """
    cfg = cfg or YahooMetricsConfig()

    unique_tickers: List[str] = sorted({str(t).strip().upper() for t in tickers if str(t).strip()})
    if not unique_tickers:
        return pd.DataFrame(columns=[
            "Ticker", "Yahoo_SubSector", "Sharpe_1Y", "Sharpe_3Y",
            "Z_Score_1Y", "Z_Score_3Y", "Yahoo_Fetch_Error",
        ])

    subsector_cache = _load_subsector_cache(cfg.subsector_cache_path)
    cache_hits_before = len(subsector_cache)
    holding_info_cache: Dict[str, Any] = {}

    errors: List[str] = []

    # Sub-sectors: cached tickers return immediately; the rest are looked up
    # in parallel (each lookup is several small Yahoo requests).
    def _subsector(ticker: str) -> Tuple[str, str, List[str]]:
        errs: List[str] = []
        sub = resolve_ticker_subsector(
            ticker, cfg, errors=errs,
            subsector_cache=subsector_cache,
            holding_info_cache=holding_info_cache,
        )
        return ticker, sub, errs

    print(f"  [Yahoo Metrics] Sub-sectors for {len(unique_tickers)} tickers "
          f"({cfg.subsector_workers} parallel lookups for any not cached)...")
    sub_sectors: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max(1, cfg.subsector_workers)) as pool:
        for ticker, sub, errs in pool.map(_subsector, unique_tickers):
            sub_sectors[ticker] = sub
            errors.extend(errs)

    # Sharpe: one price download per batch (yfinance threads each batch).
    batches = [unique_tickers[i:i + cfg.batch_size] for i in range(0, len(unique_tickers), cfg.batch_size)]
    sharpe_results: Dict[str, Dict[str, float]] = {}
    for batch_idx, batch in enumerate(batches, start=1):
        print(f"  [Yahoo Metrics] Prices batch {batch_idx}/{len(batches)} ({len(batch)} tickers)...")
        daily_prices = _download_price_history(batch, cfg, errors=errors)
        sharpe_results.update(_compute_sharpe_for_batch(daily_prices, batch, cfg, errors=errors))
        if batch_idx < len(batches):
            time.sleep(cfg.rest_delay_seconds + random.uniform(0, cfg.rest_delay_jitter_seconds))

    if errors:
        print(f"  [Yahoo Metrics] {len(errors)} issue(s) (first 20 shown):")
        for msg in errors[:20]:
            print(f"    - {msg}")

    ticker_error_map: Dict[str, str] = {}
    for msg in errors:
        ticker_error_map.setdefault(msg.split(":", 1)[0].strip(), msg)

    records: List[dict] = [
        {
            "Ticker": ticker,
            "Yahoo_SubSector": sub_sectors.get(ticker, DEFAULT_SUBSECTOR),
            "Sharpe_1Y": sharpe_results.get(ticker, {}).get("Sharpe_1Y", np.nan),
            "Sharpe_3Y": sharpe_results.get(ticker, {}).get("Sharpe_3Y", np.nan),
            "Yahoo_Fetch_Error": ticker_error_map.get(ticker, ""),
        }
        for ticker in unique_tickers
    ]

    _save_subsector_cache(cfg.subsector_cache_path, subsector_cache)
    cache_hits_after = len(subsector_cache) - cache_hits_before
    print(
        f"  [Yahoo Metrics] Sub-sector cache: {cache_hits_before} entrie(s) loaded, "
        f"{cache_hits_after} new/refreshed, saved to {cfg.subsector_cache_path}"
    )

    df_matrix = add_subsector_z_scores(pd.DataFrame.from_records(records))

    if cfg.log_unmapped_keys and unmapped_key_log:
        print(f"\n[Yahoo Metrics] {len(unmapped_key_log)} unmapped industryKey/sectorKey pair(s):")
        for ind_key, sec_key in sorted(unmapped_key_log):
            print(f"  - industryKey='{ind_key}'  sectorKey='{sec_key}'")
        print("Add matching keywords to SUBSECTOR_KEYWORDS to close these gaps.\n")

    ordered_cols = [
        "Ticker", "Yahoo_SubSector", "Sharpe_1Y", "Sharpe_3Y",
        "Z_Score_1Y", "Z_Score_3Y", "Yahoo_Fetch_Error",
    ]
    return df_matrix[ordered_cols]
