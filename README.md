# ETF Fund Screener

A Python-based tool that analyzes and ranks Exchange-Traded Funds (ETFs) based on multiple financial metrics to help you identify the best funds for your investment strategy.

## What This Tool Does

This screener evaluates ETFs across **8 key performance dimensions** and produces a ranked list of top funds within each investment category. It helps you:

- **Find top-performing ETFs** based on historical returns, risk-adjusted performance, and costs
- **Compare funds fairly** by normalizing scores within each Morningstar Category (so you're comparing apples to apples)
- **Apply custom filters** to exclude funds that don't meet your criteria (e.g., expense ratio limits, fund size requirements)
- **Export results** to Excel with clear rankings and scores for easy review

## Key Features

### 8 Scoring Dimensions
Each ETF is scored (0-100) on these concepts:

1. **Performance** - Historical returns (1Y, 3Y, 5Y) and category rankings
2. **Risk-Adjusted Return** - Sharpe ratios, upside/downside capture ratios
3. **Volatility** - Standard deviation and maximum drawdown (lower is better)
4. **Tracking Quality** - How closely the fund follows its benchmark (lower tracking error is better)
5. **Liquidity & Size** - Fund assets under management and trading volume
6. **Quality & Valuation** - Portfolio growth grades, financial health, and price vs. fair value
7. **Costs** - Expense ratios and management fees (lower is better)
8. **Tax & Income** - Tax efficiency and dividend yield

### Smart Ranking
- Scores are **normalized within each Morningstar Category** (e.g., Technology ETFs are compared to other Technology ETFs, not to Utilities)
- You get **two rankings**: top funds per category AND top funds overall
- Missing data doesn't penalize funds - scores only use available metrics

### Flexible Configuration
- All settings are controlled via **YAML configuration files** - no code changes needed
- Adjust weights for each scoring dimension to match your investment priorities
- Set custom thresholds for filters (expense ratio caps, minimum fund size, etc.)
- Easy to create multiple "profiles" for different investment strategies

## Quick Start

### Prerequisites
```bash
pip install -r requirements.txt
```

### Running the Screener

1. **Prepare your input files** (Morningstar Excel exports):
   - Structural data file (e.g., `python-etfs.xlsx`)
   - Performance data file (e.g., `performance-etfs.xlsx`)

2. **Create or edit a profile configuration** (e.g., `input_files/input_profile_a.yaml`):
   ```yaml
   struct_path: "python-etfs.xlsx"
   perf_path: "performance-etfs.xlsx"
   out_path: "output"
   profile_name: "A"
   top_n_per_category: 5
   thresholds:
     max_expense_ratio: 0.75
     require_fund_size: true
     exclude_leveraged_funds: true
   ```

3. **Run the screener**:
   ```bash
   cd etf_screener
   python main.py
   ```

4. **Review the output**:
   - Results are saved to the `output/` directory with timestamped filenames
   - Excel files include formatted headers and all scoring details
   - Console output shows a summary of top selections

## Understanding the Output

### Excel Output Columns
- **Profile_X_Score** - Composite score (0-100) based on weighted average of all 8 concepts
- **Profile_X_Rank_In_Category** - Rank within the fund's Morningstar Category (1 = best)
- **Profile_X_Selected_Flag** - True if this fund is in the top N for its category
- **Profile_X_Rank_Overall** - Rank across all eligible funds
- **Concept scores** - Individual scores for each of the 8 dimensions (Performance_Score, Risk_Adjusted_Score, etc.)
- **Raw metrics** - Original data from Morningstar for reference

### Console Summary
The script prints:
- Number of funds selected per category
- Top N funds overall
- Any data quality warnings (e.g., missing Yahoo Finance data)

## Customization

### Adjusting Weights
Edit the `weights` section in your YAML file to change how much each concept counts:

```yaml
thresholds:
  weights:
    performance: 0.30      # Increase emphasis on returns
    risk_adjusted: 0.25     # Emphasize risk-adjusted performance
    volatility: 0.10       # Reduce emphasis on volatility
    costs: 0.20            # Increase emphasis on low fees
    # ... etc
```

### Fine-Tuning Within Concepts
You can also adjust weights for individual metrics within each concept:

```yaml
thresholds:
  concept_weights:
    performance:
      return_3y: 0.50      # Emphasize 3-year returns more
      return_5y: 0.30
      return_1y: 0.10
      rank_3y: 0.10
```

### Adding Filters
Add or modify eligibility filters in the YAML:

```yaml
thresholds:
  require_3y_return: true           # Only funds with 3-year history
  min_fund_size: 100000000           # Minimum $100M AUM
  max_expense_ratio: 0.50           # Maximum 0.50% expense ratio
  exclude_leveraged_funds: true     # No 2x/3x leveraged funds
```

## Project Structure

```
ETF-Fund-Screener/
├── etf_screener/
│   ├── main.py              # Main entry point - runs the pipeline
│   ├── config.py            # Default settings and weights
│   ├── data_loading.py      # Loads Excel data files
│   ├── merging.py           # Merges structural and performance data
│   ├── scoring.py           # Calculates all concept scores
│   ├── export.py            # Exports results to Excel
│   ├── input_file.py        # Handles YAML configuration loading
│   ├── profiles/            # Investment strategy profiles
│   │   └── profile_a.py    # Profile A: long-term, low-risk strategy
│   ├── docs/                # Detailed technical documentation
│   │   ├── column_glossary.md      # Definitions of all metrics
│   │   └── profile_a_design.md     # Profile A design details
│   └── input_files/        # Configuration file templates
│       └── input_profile_a.yaml
├── eTrade/                  # eTrade-specific integration scripts
├── requirements.txt         # Python dependencies
└── README.md               # This file
```

## Data Sources

- **Morningstar** - Primary data source for structural and performance metrics (via Excel exports)
- **Yahoo Finance** - Additional metrics (Sharpe ratios, Z-scores) fetched via API

## Current Limitations

- Sector composition analysis is not yet implemented (e.g., distinguishing software vs. hardware within Technology sector)
- Only Profile A is currently implemented (long-term, low-risk strategy)
- Requires Morningstar Excel exports as input data

## Future Enhancements

Potential improvements:
- Add more investment profiles (e.g., aggressive growth, income-focused)
- Implement sector/sub-sector analysis for more granular comparisons
- Add backtesting capabilities to validate historical performance
- Support additional data sources beyond Morningstar

## Documentation

For detailed technical information, see:
- `etf_screener/docs/column_glossary.md` - Complete definitions and formulas for all metrics
- `etf_screener/docs/profile_a_design.md` - Detailed design documentation for Profile A

## Support

This tool is designed for investors who want to systematically evaluate ETFs using quantitative metrics. It requires basic Python knowledge to run and configure, but the Excel outputs are designed to be readable without programming expertise.
