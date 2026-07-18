import os
import time
from datetime import datetime
import numpy as np
import pandas as pd
import yfinance as yf

# =========================================================================
# CONFIGURATION PARAMETERS (Scale Optimizers & Fallbacks)
# =========================================================================
INPUT_FILE = "tickers.txt"           # Target file containing your tickers
BATCH_SIZE = 20                      # Number of tickers processed per batch
REST_DELAY_SECONDS = 3.5             # Anti-throttling delay between batches
SAMPLE_STOCK_LOOKUPS = 5             # Sample size reduction to speed up holding loops
MAX_DOWNLOAD_RETRIES = 3             # Number of times to retry failed network batches
LOG_UNMAPPED_KEYS = True             # Print any industryKey/sectorKey not covered by the taxonomy below

rf_monthly = 0.04 / 12  # Static monthly risk-free benchmark proxy (4% annualized / 12)

# =========================================================================
# SECTOR / SUB-SECTOR TAXONOMY
# (Derived from docs/Financial Sectors and Niche Sub-Sectors.rtf --
#  11 core sectors, ~33 sub-sectors. Keys below are matched against
#  yfinance's industryKey / sectorKey fields.)
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

# Flatten into a single lookup: sub_sector_label -> keyword list
SUBSECTOR_KEYWORDS = {
    sub_label: keywords
    for sector, subsectors in SECTOR_TAXONOMY.items()
    for sub_label, keywords in subsectors.items()
}

unmapped_key_log = set()


def classify_holding_subsector(ind_key: str, sec_key: str) -> str:
    """
    Match a stock's industryKey/sectorKey against the full sub-sector
    taxonomy (SUBSECTOR_KEYWORDS). Falls back to 'Broad Market Equity'
    if nothing matches, and logs the unmatched pair for later tuning.
    """
    combined = f"{ind_key} {sec_key}".lower()
    for sub_label, keywords in SUBSECTOR_KEYWORDS.items():
        if any(kw in combined for kw in keywords):
            return sub_label
    if LOG_UNMAPPED_KEYS and (ind_key or sec_key):
        unmapped_key_log.add((ind_key, sec_key))
    return "Broad Market Equity"


# Standard sector proxy mappings used exclusively to prevent statistical group math from crashing
sector_proxies = {
    "Technology - Software & Services": "IGV",
    "Technology - Semiconductors (Chips)": "SOXX",
    "Technology - Broad Growth / Hardware": "XLK",
    "Broad Market Equity": "SPY",
    "Income / High-Yield Strategy": "JEPI",
    "Defensive - Healthcare": "XLV",
    "Semiconductors & Semiconductor Equipment": "SOXX",
    "Software & Services": "IGV",
    "Biotechnology": "XBI",
    "Pharmaceuticals": "XPH",
    "Banks": "KBE",
    "Financial Services": "XLF",
    "Insurance": "KIE",
}

# =========================================================================
# 1. READ AND HARDEN INITIALIZATION FILE POOL
# =========================================================================
if not os.path.exists(INPUT_FILE):
    print(f"\n[FATAL ERROR]: Source input file '{INPUT_FILE}' not found.")
    print("Please generate a simple 'tickers.txt' file filled with target tickers to proceed.")
    exit(1)

try:
    with open(INPUT_FILE, "r", encoding="utf-8", errors="ignore") as f:
        raw_content = f.read()
except Exception as e:
    print(f"\n[FATAL ERROR]: Failed to read '{INPUT_FILE}'. Disk/Permission Error: {e}")
    exit(1)

processed_tickers = []
for line in raw_content.replace(",", "\n").replace("\t", "\n").split("\n"):
    clean_ticker = line.strip().upper()
    if clean_ticker and not clean_ticker.startswith("#"):
        processed_tickers.append(clean_ticker)

user_tickers = list(sorted(set(processed_tickers)))
total_tickers = len(user_tickers)

if total_tickers == 0:
    print(f"\n[FATAL ERROR]: '{INPUT_FILE}' is empty or contains no valid tickers.")
    exit(1)

print(f"Successfully loaded {total_tickers} unique tickers from '{INPUT_FILE}'.")
print(f"Executing deep look-through metrics across {BATCH_SIZE}-asset chunks...\n")

ticker_batches = [user_tickers[i:i + BATCH_SIZE] for i in range(0, total_tickers, BATCH_SIZE)]
global_records = []

# =========================================================================
# 2. BATCHED EXECUTION PIPELINE LOOP
# =========================================================================
for batch_idx, current_batch in enumerate(ticker_batches, start=1):
    print(f"--- Processing Batch {batch_idx}/{len(ticker_batches)} ({len(current_batch)} Assets) ---")

    ticker_to_sector = {}
    batch_download_queue = list(current_batch)

    # --- PHASE A: DYNAMIC LOOK-THROUGH ACCUMULATION ---
    for ticker in current_batch:
        resolved_sector = "Broad Market Equity"
        try:
            t_obj = yf.Ticker(ticker)
            f_data = t_obj.funds_data
            holdings_df = f_data.top_holdings if f_data is not None else None

            if holdings_df is not None and not holdings_df.empty:
                weight_matrix = {}  # UPDATED: now dynamic across the full sub-sector taxonomy
                                     # instead of the old hardcoded 5-key dict

                top_stocks = holdings_df.index.tolist()
                loop_limit = min(len(top_stocks), SAMPLE_STOCK_LOOKUPS)

                for stock_symbol in top_stocks[:loop_limit]:
                    try:
                        stock_symbol = str(stock_symbol).strip().upper()

                        # Skip non-equity holding symbols (futures, options, cash sleeves,
                        # synthetic placeholders, etc.) that can appear inside ETF
                        # top_holdings tables and trigger noisy Yahoo 404 lookups.
                        if not stock_symbol:
                            continue
                        if any(ch in stock_symbol for ch in ["=", "/", "^"]):
                            continue
                        if len(stock_symbol) > 5 and stock_symbol[-3:].isalnum() and any(ch.isdigit() for ch in stock_symbol[-3:]):
                            continue
                        if not stock_symbol.replace(".", "").replace("-", "").isalnum():
                            continue

                        s_info = yf.Ticker(stock_symbol).info
                        if not s_info:
                            continue
                        ind_key = str(s_info.get("industryKey", "")).lower() if s_info.get("industryKey", "") else ""
                        sec_key = str(s_info.get("sectorKey", "")).lower() if s_info.get("sectorKey", "") else ""

                        raw_weight = holdings_df.loc[stock_symbol].get("Holding Percent", 0.0)
                        holding_weight = float(raw_weight) if raw_weight is not None else 0.0

                        # UPDATED: replaced the old 4-way if/elif chain with a taxonomy-driven
                        # classifier that checks all ~33 sub-sectors instead of just 4 buckets.
                        sub_sector = classify_holding_subsector(ind_key, sec_key)
                        weight_matrix[sub_sector] = weight_matrix.get(sub_sector, 0.0) + holding_weight
                    except Exception:
                        continue

                if weight_matrix:
                    max_industry = max(weight_matrix, key=weight_matrix.get)
                    if weight_matrix[max_industry] > 0:
                        resolved_sector = max_industry
            else:
                t_info = t_obj.info or {}
                summary = str(t_info.get("longBusinessSummary", "")).lower() if t_info.get("longBusinessSummary",
                                                                                           "") else ""

                if "semiconductor" in summary or "chips" in summary:
                    resolved_sector = "Technology - Semiconductors (Chips)"
                elif "software" in summary or "cloud" in summary:
                    resolved_sector = "Technology - Software & Services"
                elif "healthcare" in summary:
                    resolved_sector = "Defensive - Healthcare"
                elif "dividend" in summary or "income" in summary:
                    resolved_sector = "Income / High-Yield Strategy"

        except Exception:
            pass

        ticker_to_sector[ticker] = resolved_sector
        if resolved_sector in sector_proxies:
            batch_download_queue.append(sector_proxies[resolved_sector])

    batch_download_queue.extend(["SPY", "QQQ", "XLK", "SOXX", "IGV"])
    batch_download_queue = list(set(batch_download_queue))

    # --- PHASE B: CHUNK PRICING DOWNLOAD MATRIX W/ RETRIES ---
    raw_data = pd.DataFrame()
    for attempt in range(1, MAX_DOWNLOAD_RETRIES + 1):
        try:
            raw_data = yf.download(batch_download_queue, period="3y", interval="1d", auto_adjust=False, progress=False)
            if not raw_data.empty:
                break
        except Exception as download_error:
            if attempt == MAX_DOWNLOAD_RETRIES:
                print(f"  [ERROR] Failed pricing download after {MAX_DOWNLOAD_RETRIES} attempts: {download_error}")
            else:
                print(f"  [Warning] Download attempt {attempt} failed. Retrying in 2 seconds...")
                time.sleep(2)

    # --- PHASE C: LOCAL PERFORMANCE EXTRACTION ---
    try:
        if not raw_data.empty and "Adj Close" in raw_data.columns:
            daily_prices = raw_data.xs("Adj Close", axis=1, level=0) if isinstance(raw_data.columns, pd.MultiIndex) else \
            raw_data["Adj Close"]
            monthly_prices = daily_prices.resample("ME").last()
            all_monthly_returns = monthly_prices.pct_change().dropna()

            returns_3y = all_monthly_returns.copy()
            returns_1y = all_monthly_returns.tail(12).copy()

            for ticker in current_batch:
                if ticker in all_monthly_returns.columns:
                    try:
                        exc_1y = returns_1y[ticker] - rf_monthly
                        std_1y = exc_1y.std()
                        sharpe_1y = (exc_1y.mean() / std_1y) * np.sqrt(12) if (
                                    std_1y > 0 and not pd.isna(std_1y)) else np.nan

                        exc_3y = returns_3y[ticker] - rf_monthly
                        std_3y = exc_3y.std()
                        sharpe_3y = (exc_3y.mean() / std_3y) * np.sqrt(12) if (
                                    std_3y > 0 and not pd.isna(std_3y)) else np.nan

                        global_records.append({
                            "Ticker": ticker,
                            "Calculated_Sector": ticker_to_sector.get(ticker, "Broad Market Equity"),
                            "Sharpe_1Y": sharpe_1y,
                            "Sharpe_3Y": sharpe_3y
                        })
                    except Exception as calc_err:
                        print(f"  [Skip Error] Calculation failed for ticker {ticker}: {calc_err}")
                else:
                    global_records.append({
                        "Ticker": ticker,
                        "Calculated_Sector": ticker_to_sector.get(ticker, "Broad Market Equity"),
                        "Sharpe_1Y": np.nan,
                        "Sharpe_3Y": np.nan
                    })
        else:
            print(f"  [Warning] Batch {batch_idx} returned empty data matrices. Logging placeholders.")
            for ticker in current_batch:
                global_records.append({
                    "Ticker": ticker,
                    "Calculated_Sector": ticker_to_sector.get(ticker, "Broad Market Equity"),
                    "Sharpe_1Y": np.nan,
                    "Sharpe_3Y": np.nan
                })
    except Exception as batch_pipeline_error:
        print(f"  [CRITICAL BATCH ERROR] Extraction failed on chunk block {batch_idx}: {batch_pipeline_error}")

    if batch_idx < len(ticker_batches):
        print(f"  Anti-throttling cooldown... Sleeping for {REST_DELAY_SECONDS} seconds.")
        time.sleep(REST_DELAY_SECONDS)

# =========================================================================
# 3. GLOBAL STATISTICAL CALCULATIONS (Across Aggregate File Pool)
# =========================================================================
print("\nFinalizing calculations across all processed records...")
if not global_records:
    print("[FATAL FAILURE]: Data collection pipeline ended with zero records. Output blocked.")
    exit(1)

df_matrix = pd.DataFrame(global_records)

try:
    df_matrix["Z_Score_1Y"] = df_matrix.groupby("Calculated_Sector")["Sharpe_1Y"].transform(
        lambda x: (x - x.mean()) / x.std() if (x.std() > 0 and not pd.isna(x.std())) else 0.0
    )
    df_matrix["Z_Score_3Y"] = df_matrix.groupby("Calculated_Sector")["Sharpe_3Y"].transform(
        lambda x: (x - x.mean()) / x.std() if (x.std() > 0 and not pd.isna(x.std())) else 0.0
    )
except Exception as z_error:
    print(f"[Warning] Relative Z-score calculation failed due to category distribution imbalances: {z_error}")
    df_matrix["Z_Score_1Y"] = 0.0
    df_matrix["Z_Score_3Y"] = 0.0


# --- DECISION ROUTER ENGINE ---
def generate_signal(row):
    if pd.isna(row["Sharpe_1Y"]) or row["Sharpe_1Y"] < 0:
        return "AVOID (Negative Absolute Performance Basis)"

    z1 = 0.0 if pd.isna(row["Z_Score_1Y"]) else row["Z_Score_1Y"]
    z3 = 0.0 if pd.isna(row["Z_Score_3Y"]) else row["Z_Score_3Y"]

    if row["Sharpe_1Y"] >= 1.0 and z1 > 0 and z3 > 0:
        return f"STRONG BUY (Top Tier {row['Calculated_Sector']} Selection)"
    elif row["Sharpe_1Y"] >= 0.5 and z1 > 0.5:
        if z3 < 0:
            return "TACTICAL BUY (Short Sector Momentum)"
        return "HOLD / ACCUMULATE (Healthy Core Strategy Asset)"
    elif z1 < 0 and z3 > 0.5:
        if row["Sharpe_1Y"] >= 0.3:
            return "BUY THE DIP (Long-Term Structural Industry Outlier)"
        return "WATCHLIST (Weak Near-Term Sector Footing)"
    else:
        return "UNDERPERFORMER (Weak Sector Position)"


df_matrix["Decision"] = df_matrix.apply(generate_signal, axis=1)
df_matrix = df_matrix.sort_values(by=["Decision", "Calculated_Sector", "Z_Score_3Y"], ascending=[True, True, False])

# =========================================================================
# UNMAPPED KEY DIAGNOSTIC REPORT (added alongside sector classification update)
# Prints every industryKey/sectorKey pair that fell through to
# 'Broad Market Equity' so SUBSECTOR_KEYWORDS can be tuned with real,
# observed Yahoo keys rather than guessed substrings.
# =========================================================================
if LOG_UNMAPPED_KEYS and unmapped_key_log:
    print(f"\n[DIAGNOSTIC] {len(unmapped_key_log)} unmapped industryKey/sectorKey pair(s) found:")
    for ind_key, sec_key in sorted(unmapped_key_log):
        print(f"  - industryKey='{ind_key}'  sectorKey='{sec_key}'")
    print("Add matching keywords to SUBSECTOR_KEYWORDS above to close these gaps.\n")
elif LOG_UNMAPPED_KEYS:
    print("\n[DIAGNOSTIC] No unmapped industryKey/sectorKey pairs found -- taxonomy covered everything this run.\n")

# =========================================================================
# 4. AUTOMATED CSV TIMESTAMPED EXPORT (Sanitized String Formatting)
# =========================================================================
try:
    base_filename, _ = os.path.splitext(INPUT_FILE)
    timestamp_str = datetime.now().strftime("%Y-%m-%d_%H%M")
    csv_filename = f"{base_filename}_result_{timestamp_str}.csv"

    print(f"Writing sanitized metrics out to timestamped CSV file: '{csv_filename}'...")
    df_matrix.to_csv(csv_filename, index=False, na_rep="NaN")
    print(f"\n[Pipeline Complete]: File processing execution ended successfully.\nOutput File: '{csv_filename}'")

except Exception as file_write_error:
    print(f"\n[CRITICAL WRITE ERROR]: Could not write out final data file to disk: {file_write_error}")
