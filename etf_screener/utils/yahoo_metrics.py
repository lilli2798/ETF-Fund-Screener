"""Consolidated, reusable Yahoo Finance metrics for the ETF screener.

This module is the single source of truth for everything derived from
Yahoo Finance: sub-sector classification (via top-holdings look-through),
Sharpe Ratio (1Y/3Y), and sector-relative Z-Scores. It supersedes the
sub-sector-only logic that used to live in yahoo_subsector.py (kept as a
thin backward-compatible shim) and the inline logic in get_yahoo_dta.py
(which is now a thin CLI wrapper around get_yahoo_metrics_for_tickers()).

Design goals:
  - Callable two ways: pass a list of tickers directly (main.py's CI
    flow, using tickers already present in the merged Morningstar
    dataframe), or read tickers from a tickers.txt-style file (standalone
    local runs via get_yahoo_dta.py, useful for testing against an
    arbitrary watchlist independent of the spreadsheet universe).
  - Every per-ticker Yahoo Finance call is wrapped so a single bad/
    delisted/rate-limited ticker never aborts the whole batch -- failures
    are logged and the ticker gets safe NaN/default placeholders instead.
  - All tunables (batch size, rest delay, retries, sample size) accept
    overrides so they can be driven from the profile input YAML's
    thresholds.yahoo_metrics block (see config.py DEFAULT_YAHOO_METRICS
    and input_file.py's deep-merge), instead of being hardcoded.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd
import yfinance as yf

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
    """Tunables for the Yahoo fetch pipeline. All fields are overridable
    from thresholds.yahoo_metrics in the profile input YAML (see
    config.DEFAULT_YAHOO_METRICS + input_file.deep_merge_dicts), so
    behavior can be tuned per-profile without editing code.
    """
    batch_size: int = 20
    rest_delay_seconds: float = 3.5
    sample_stock_lookups: int = 5
    max_download_retries: int = 3
    risk_free_annual: float = 0.04
    price_history_period: str = "3y"
    log_unmapped_keys: bool = True

    @property
    def risk_free_monthly(self) -> float:
        return self.risk_free_annual / 12

    @classmethod
    def from_thresholds(cls, thresholds: Optional[dict]) -> "YahooMetricsConfig":
        """Build a config from a profile input YAML's thresholds dict,
        e.g. thresholds["yahoo_metrics"] = {"batch_size": 25, ...}.
        Unknown/omitted keys fall back to the dataclass defaults above.
        """
        overrides = (thresholds or {}).get("yahoo_metrics", {}) or {}
        valid_fields = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in overrides.items() if k in valid_fields}
        return cls(**filtered)


# =========================================================================
# TICKER INPUT HELPERS
# =========================================================================

def read_tickers_from_file(path: str) -> List[str]:
    """Read a tickers.txt-style file: comma/tab/newline separated, '#'
    comment lines ignored, deduplicated and sorted. Used only by the
    standalone CLI (get_yahoo_dta.py) for ad hoc local runs -- the CI
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


def resolve_ticker_subsector(
    ticker: str,
    cfg: YahooMetricsConfig,
    errors: Optional[List[str]] = None,
) -> str:
    """For a single ETF ticker, look through its top holdings, classify
    each holding's industryKey/sectorKey, and return the sub-sector with
    the highest aggregated holding weight. Returns DEFAULT_SUBSECTOR on
    any missing/errored data -- never raises, so one bad ticker can't
    abort a batch. Any handled exception is appended to `errors` (if
    provided) for later diagnostic reporting.
    """
    try:
        t_obj = yf.Ticker(ticker)
        f_data = t_obj.funds_data
        holdings_df = f_data.top_holdings if f_data is not None else None
    except Exception as exc:
        if errors is not None:
            errors.append(f"{ticker}: failed to fetch funds_data ({exc})")
        return DEFAULT_SUBSECTOR

    if holdings_df is None or holdings_df.empty:
        if errors is not None:
            errors.append(f"{ticker}: no top_holdings data available (non-ETF or unsupported by Yahoo)")
        return DEFAULT_SUBSECTOR

    weight_matrix: Dict[str, float] = {}
    top_stocks = holdings_df.index.tolist()
    loop_limit = min(len(top_stocks), cfg.sample_stock_lookups)

    for stock_symbol in top_stocks[:loop_limit]:
        try:
            stock_symbol = str(stock_symbol).strip().upper()
            if _is_skippable_holding_symbol(stock_symbol):
                continue

            s_info = yf.Ticker(stock_symbol).info
            if not s_info:
                continue
            ind_key = str(s_info.get("industryKey", "")).lower() if s_info.get("industryKey", "") else ""
            sec_key = str(s_info.get("sectorKey", "")).lower() if s_info.get("sectorKey", "") else ""

            raw_weight = holdings_df.loc[stock_symbol].get("Holding Percent", 0.0)
            holding_weight = float(raw_weight) if raw_weight is not None else 0.0

            sub_sector = classify_holding_subsector(ind_key, sec_key, log_unmapped=cfg.log_unmapped_keys)
            weight_matrix[sub_sector] = weight_matrix.get(sub_sector, 0.0) + holding_weight
        except Exception:
            continue

    if weight_matrix:
        max_sub_sector = max(weight_matrix, key=weight_matrix.get)
        if weight_matrix[max_sub_sector] > 0:
            return max_sub_sector

    return DEFAULT_SUBSECTOR


# =========================================================================
# SHARPE RATIO (via batched price history)
# =========================================================================

def _download_price_history(
    tickers: List[str],
    cfg: YahooMetricsConfig,
    errors: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Download adjusted-close price history for a batch of tickers,
    retrying on failure. Returns an empty DataFrame (never raises) if
    every attempt fails, so callers can fall back to NaN Sharpe values
    instead of crashing the whole pipeline.
    """
    raw_data = pd.DataFrame()
    for attempt in range(1, cfg.max_download_retries + 1):
        try:
            raw_data = yf.download(
                tickers, period=cfg.price_history_period, interval="1d",
                auto_adjust=False, progress=False,
            )
            if not raw_data.empty:
                break
        except Exception as exc:
            if attempt == cfg.max_download_retries:
                msg = f"Price download failed after {cfg.max_download_retries} attempts: {exc}"
                print(f"  [Yahoo Metrics] [ERROR] {msg}")
                if errors is not None:
                    errors.append(msg)
            else:
                time.sleep(2)
    return raw_data


def _compute_sharpe_for_batch(
    raw_data: pd.DataFrame,
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

    if raw_data.empty or "Adj Close" not in raw_data.columns:
        if errors is not None:
            errors.append("Batch price data empty or missing 'Adj Close' -- Sharpe left as NaN for this batch.")
        return results

    daily_prices = (
        raw_data.xs("Adj Close", axis=1, level=0)
        if isinstance(raw_data.columns, pd.MultiIndex)
        else raw_data["Adj Close"]
    )
    monthly_prices = daily_prices.resample("ME").last()
    all_monthly_returns = monthly_prices.pct_change().dropna()

    returns_3y = all_monthly_returns.copy()
    returns_1y = all_monthly_returns.tail(12).copy()
    rf_monthly = cfg.risk_free_monthly

    for ticker in tickers:
        if ticker not in all_monthly_returns.columns:
            if errors is not None:
                errors.append(f"{ticker}: no price series returned by Yahoo -- Sharpe left as NaN.")
            continue
        try:
            exc_1y = returns_1y[ticker] - rf_monthly
            std_1y = exc_1y.std()
            sharpe_1y = (exc_1y.mean() / std_1y) * np.sqrt(12) if (std_1y > 0 and not pd.isna(std_1y)) else np.nan

            exc_3y = returns_3y[ticker] - rf_monthly
            std_3y = exc_3y.std()
            sharpe_3y = (exc_3y.mean() / std_3y) * np.sqrt(12) if (std_3y > 0 and not pd.isna(std_3y)) else np.nan

            results[ticker] = {"Sharpe_1Y": sharpe_1y, "Sharpe_3Y": sharpe_3y}
        except Exception as exc:
            if errors is not None:
                errors.append(f"{ticker}: Sharpe calculation failed ({exc}) -- left as NaN.")

    return results


# =========================================================================
# MAIN ENTRY POINT
# =========================================================================

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

    batches = [unique_tickers[i:i + cfg.batch_size] for i in range(0, len(unique_tickers), cfg.batch_size)]
    records: List[dict] = []

    for batch_idx, batch in enumerate(batches, start=1):
        print(f"  [Yahoo Metrics] Batch {batch_idx}/{len(batches)} ({len(batch)} tickers)...")
        batch_errors: List[str] = []

        sub_sectors: Dict[str, str] = {}
        for ticker in batch:
            sub_sectors[ticker] = resolve_ticker_subsector(ticker, cfg, errors=batch_errors)

        raw_data = _download_price_history(batch, cfg, errors=batch_errors)
        sharpe_results = _compute_sharpe_for_batch(raw_data, batch, cfg, errors=batch_errors)

        if batch_errors:
            print(f"  [Yahoo Metrics] {len(batch_errors)} issue(s) in batch {batch_idx}:")
            for msg in batch_errors:
                print(f"    - {msg}")

        ticker_error_map: Dict[str, str] = {}
        for msg in batch_errors:
            t = msg.split(":", 1)[0].strip()
            ticker_error_map.setdefault(t, msg)

        for ticker in batch:
            records.append({
                "Ticker": ticker,
                "Yahoo_SubSector": sub_sectors.get(ticker, DEFAULT_SUBSECTOR),
                "Sharpe_1Y": sharpe_results.get(ticker, {}).get("Sharpe_1Y", np.nan),
                "Sharpe_3Y": sharpe_results.get(ticker, {}).get("Sharpe_3Y", np.nan),
                "Yahoo_Fetch_Error": ticker_error_map.get(ticker, ""),
            })

        if batch_idx < len(batches):
            time.sleep(cfg.rest_delay_seconds)

    df_matrix = pd.DataFrame.from_records(records)

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
