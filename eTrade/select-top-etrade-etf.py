import pandas as pd
import numpy as np
import re
from pathlib import Path

FILE_PATH = "Screener-Export.xls"
OUT_DIR = Path(
    "/Users/lihongfeng/Library/CloudStorage/OneDrive-Personal/AA-FundResearchProject/A-Do-Not-Delete-DB/merged/StockAnalysis"
)
OUT_DIR.mkdir(exist_ok=True)

SCREENED_XLSX = OUT_DIR / "Screener-Export-screened.xlsx"

# -------------------------------------------------
# 1. Read sheets and merge into one DataFrame
# -------------------------------------------------
overview = pd.read_excel(FILE_PATH, sheet_name="Overview")
performance = pd.read_excel(FILE_PATH, sheet_name="Performance")
portfolio = pd.read_excel(FILE_PATH, sheet_name="Portfolio")
risk = pd.read_excel(FILE_PATH, sheet_name="Risk")

df = (
    overview
    .merge(performance, on="ETF Name", how="left")
    .merge(portfolio, on="ETF Name", how="left")
    .merge(risk, on="ETF Name", how="left")
)

# -------------------------------------------------
# 2. Model_Symbol from LAST (TICKER)
# -------------------------------------------------
df["Model_Symbol"] = (
    df["ETF Name"].astype(str).str.extract(r"\(([A-Z0-9.-]+)\)\s*$")
)

# -------------------------------------------------
# 3. Clean numeric fields in a copy for scoring
# -------------------------------------------------
pct_cols = [
    "Expense Ratio", "1 Yr Return", "3 Yr Return",
    "5 Yr Return", "10 Yr Return", "Since Inception Return", "Yield",
]

num_cols = [
    "Morningstar Rating",
    "Previous Close vs. NAV", "Premium Discount",
    "Turnover Ratio", "Portfolio Concentration",
    "Avg. Market Cap", "Price/Prospective Earnings",
    "3-Year Alpha", "3-Year Beta vs. Benchmark",
    "3-Year Sharpe Ratio", "3-Year R-Squared",
    "Index Corr. 3 Yr S&P 500", "Index Corr. 3 Yr Morningstar",
]


def clean_percent(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str)
        .str.replace("%", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.replace(",", "", regex=False)
        .replace("--", np.nan),
        errors="coerce",
    )


cleaned = df.copy()

for col in pct_cols:
    if col in cleaned.columns:
        cleaned[col] = clean_percent(cleaned[col])

for col in num_cols:
    if col in cleaned.columns:
        cleaned[col] = pd.to_numeric(
            cleaned[col].astype(str).replace("--", np.nan),
            errors="coerce",
        )


# -------------------------------------------------
# 4. Risk tag based on 3-Year Beta vs. Benchmark
# -------------------------------------------------
def risk_tag_from_beta(beta: float) -> str:
    if pd.isna(beta):
        return "Unknown"
    if beta <= 0.8:
        return "Low"
    if beta <= 1.2:
        return "Medium"
    return "High"


df["Model_Risk_Tag"] = cleaned["3-Year Beta vs. Benchmark"].apply(risk_tag_from_beta)

# -------------------------------------------------
# 5. Scoring configuration (within each category)
# -------------------------------------------------
higher_better = [
    "3 Yr Return",
    "5 Yr Return",
    "10 Yr Return",
    "Since Inception Return",
    "3-Year Sharpe Ratio",
    "3-Year Alpha",
    "Morningstar Rating",
]

lower_better = [
    "Expense Ratio",
    "3-Year Beta vs. Benchmark",
]

weights = {
    "3 Yr Return": 0.20,
    "5 Yr Return": 0.20,
    "10 Yr Return": 0.10,
    "Since Inception Return": 0.10,
    "3-Year Sharpe Ratio": 0.15,
    "3-Year Alpha": 0.10,
    "Morningstar Rating": 0.05,
    "Expense Ratio": 0.05,
    "3-Year Beta vs. Benchmark": 0.05,
}


def minmax(series: pd.Series, reverse: bool = False) -> pd.Series:
    """Min-max normalize to [0,1] inside each category."""
    s = series.copy()
    mn, mx = s.min(skipna=True), s.max(skipna=True)
    if pd.isna(mn) or pd.isna(mx) or mn == mx:
        out = pd.Series(0.5, index=s.index, dtype=float)
    else:
        out = (s - mn) / (mx - mn)
    if reverse:
        out = 1 - out
    med = out.median(skipna=True)
    return out.fillna(0.5 if pd.isna(med) else med)


# -------------------------------------------------
# 6. Initialize model columns on df (master)
# -------------------------------------------------
df["Model_Composite_Score"] = np.nan
df["Model_Rank_In_Category"] = np.nan
df["Model_Selected_Flag"] = False

ranked_groups = []
TOP_N = 5  # <<< select top 5 per category

# -------------------------------------------------
# 7. Compute scores and ranks by Fund Category
# -------------------------------------------------
for category, grp in cleaned.groupby("Fund Category", dropna=False):
    grp = grp.copy()
    idx = grp.index

    # start scores at 0
    comp = pd.Series(0.0, index=idx)

    # higher-better metrics
    for col in higher_better:
        if col in grp.columns:
            comp += minmax(grp[col]) * weights[col]

    # lower-better metrics (reverse)
    for col in lower_better:
        if col in grp.columns:
            comp += minmax(grp[col], reverse=True) * weights[col]

    comp = pd.to_numeric(comp, errors="coerce")
    ranks = comp.rank(method="dense", ascending=False)
    selected = ranks <= TOP_N

    # write into master df
    df.loc[idx, "Model_Composite_Score"] = comp
    df.loc[idx, "Model_Rank_In_Category"] = ranks
    df.loc[idx, "Model_Selected_Flag"] = selected

    # per-category view for CSVs (using df so it has risk tag etc.)
    grp_out = df.loc[idx].copy().sort_values("Model_Composite_Score", ascending=False)
    ranked_groups.append(grp_out)

    # per-category CSV
    safe_cat = re.sub(r"[^A-Za-z0-9]+", "_", str(category)) or "Uncategorized"
    out_path = OUT_DIR / f"etfs_{safe_cat[:40]}.csv"
    grp_out.to_csv(out_path, index=False)

# enforce numeric types on master
df["Model_Composite_Score"] = df["Model_Composite_Score"].round(4)
df["Model_Rank_In_Category"] = pd.to_numeric(df["Model_Rank_In_Category"], errors="coerce")

# -------------------------------------------------
# 8. Save the single screened workbook
# -------------------------------------------------
with pd.ExcelWriter(
        SCREENED_XLSX,
        engine="openpyxl",
) as writer:
    df.to_excel(
        writer,
        index=False,
        sheet_name="Screener_Export_Screened",
    )

# -------------------------------------------------
# 9. Build sample_selected.csv (top 5 per category)
# -------------------------------------------------
ranked_all = pd.concat(ranked_groups, ignore_index=True)

selected = ranked_all[ranked_all["Model_Selected_Flag"]].sort_values(
    ["Fund Category", "Model_Rank_In_Category"]
)

selected[
    [
        "Fund Category",
        "Model_Rank_In_Category",
        "ETF Name",
        "Model_Symbol",
        "Model_Composite_Score",
        "Model_Risk_Tag",
    ]
].to_csv(OUT_DIR / "sample_selected.csv", index=False)

print(f"Screened workbook: {SCREENED_XLSX}")
print(f"Per-category CSVs: {len(list(OUT_DIR.glob('etfs_*.csv')))} files")
print("Sample of selected ETFs:")
print(
    selected.head(10)[
        [
            "Fund Category",
            "Model_Rank_In_Category",
            "ETF Name",
            "Model_Symbol",
            "Model_Composite_Score",
            "Model_Risk_Tag",
        ]
    ]
)
