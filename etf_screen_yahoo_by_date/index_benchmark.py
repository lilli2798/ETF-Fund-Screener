"""
Index Benchmark Module

Downloads index data from Yahoo Finance and calculates total returns for
Dow Jones (^DJI), S&P 500 (^GSPC), and NASDAQ (^IXIC) to serve as
benchmarks for ETF/fund comparison.

Matches Morningstar return periods: 1W, 1M, 2M, QTD, 3M, 6M, 9M, YTD, 1Y-20Y
"""

from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf

# Index symbols
INDEXES = ["^IXIC", "^DJI", "^GSPC"]  # NASDAQ, Dow Jones, S&P 500
INDEX_NAMES = {
    "^IXIC": "NASDAQ",
    "^DJI": "Dow Jones",
    "^GSPC": "S&P 500"
}

# Get current date and calculate periods
current_date = datetime.now()
today = current_date.strftime("%Y-%m-%d")


def calculate_period_start_date(period: str) -> str:
    """
    Calculate start date for a given return period.
    
    Args:
        period: Return period (e.g., "1W", "1M", "3M", "YTD", "1Y", "5Y", "20Y")
    
    Returns:
        Start date string in YYYY-MM-DD format
    """
    if period == "1W":
        start_date = current_date - timedelta(weeks=1)
    elif period == "1M":
        start_date = current_date - timedelta(days=30)
    elif period == "2M":
        start_date = current_date - timedelta(days=60)
    elif period == "QTD":
        # Quarter to date (start of current quarter)
        current_month = current_date.month
        quarter_start_month = ((current_month - 1) // 3) * 3 + 1
        start_date = current_date.replace(month=quarter_start_month, day=1)
    elif period == "3M":
        start_date = current_date - timedelta(days=90)
    elif period == "6M":
        start_date = current_date - timedelta(days=180)
    elif period == "9M":
        start_date = current_date - timedelta(days=270)
    elif period == "YTD":
        start_date = current_date.replace(month=1, day=1)
    elif period.endswith("Y"):
        years = int(period.replace("Y", ""))
        start_date = current_date - timedelta(days=365.25 * years)
    else:
        raise ValueError(f"Unknown period: {period}")
    
    return start_date.strftime("%Y-%m-%d")


def calculate_total_return(prices: pd.Series) -> float:
    """
    Calculate total return from price series.
    
    Args:
        prices: Series of prices
    
    Returns:
        Total return as percentage
    """
    if len(prices) < 2:
        return None
    initial_price = prices.iloc[0]
    final_price = prices.iloc[-1]
    total_return = ((final_price - initial_price) / initial_price) * 100
    return total_return


def download_index_data(start_date: str, end_date: str = None) -> pd.DataFrame:
    """
    Download historical price data for all indexes.
    
    Args:
        start_date: Start date string (YYYY-MM-DD)
        end_date: End date string (YYYY-MM-DD), defaults to today
    
    Returns:
        DataFrame with adjusted close prices for all indexes
    """
    if end_date is None:
        end_date = today
    
    try:
        data = yf.download(INDEXES, start=start_date, end=end_date, threads=3)
        # yfinance returns a multi-index DataFrame, get the 'Close' column
        if isinstance(data.columns, pd.MultiIndex):
            data = data['Close']
        return data
    except Exception as e:
        print(f"Error downloading index data: {e}")
        return pd.DataFrame()


def calculate_index_returns(periods: list) -> pd.DataFrame:
    """
    Calculate total returns for all indexes across specified periods.
    
    Args:
        periods: List of return periods (e.g., ["1M", "3M", "YTD", "1Y", "5Y", "20Y"])
    
    Returns:
        DataFrame with index returns for each period
    """
    returns_data = {}
    
    for period in periods:
        start_date = calculate_period_start_date(period)
        
        # Download data for this period
        price_data = download_index_data(start_date, today)
        
        if not price_data.empty:
            period_returns = {}
            for index in INDEXES:
                if index in price_data.columns:
                    prices = price_data[index].dropna()
                    total_return = calculate_total_return(prices)
                    period_returns[index] = total_return
                else:
                    period_returns[index] = None
            
            returns_data[f"Total Return ({period})"] = period_returns
    
    # Convert to DataFrame
    df = pd.DataFrame(returns_data)
    df.index = [INDEX_NAMES.get(idx, idx) for idx in df.index]
    df.index.name = "Index"
    
    return df


def get_index_benchmark_comparison(fund_returns: pd.DataFrame, index_returns: pd.DataFrame) -> pd.DataFrame:
    """
    Compare fund returns against index benchmarks using the same logic as yahoo_get_top_return.py.
    
    Args:
        fund_returns: DataFrame with fund returns (tickers as index, return periods as columns)
        index_returns: DataFrame with index returns (indexes as index, return periods as columns)
    
    Returns:
        DataFrame with comparison metrics (better/worst percentages, etc.)
    """
    # Combine fund and index returns
    combined_returns = pd.concat([fund_returns, index_returns])
    
    # Get return period columns (exclude metadata columns if any)
    return_columns = [col for col in combined_returns.columns if col.startswith("Total Return")]
    
    # Calculate comparison metrics
    result = combined_returns.copy()
    
    # Count total columns and non-null columns for each row
    result['total_columns'] = len(return_columns)
    result['no_null_columns'] = result[return_columns].count(axis=1)
    
    # Get max and min from indexes only
    index_rows = result.index.isin(index_returns.index)
    index_df = result[index_rows][return_columns]
    
    max_values = index_df.max(axis=0)
    min_values = index_df.min(axis=0)
    
    # Compare funds against index benchmarks
    fund_rows = ~index_rows
    better_differences = result.loc[fund_rows, return_columns].values > max_values.values
    worse_differences = result.loc[fund_rows, return_columns].values < min_values.values
    
    result.loc[fund_rows, 'better'] = better_differences.sum(axis=1)
    result.loc[fund_rows, 'worst'] = worse_differences.sum(axis=1)
    result.loc[fund_rows, 'better_%'] = result.loc[fund_rows, 'better'] / result.loc[fund_rows, 'no_null_columns']
    result.loc[fund_rows, 'worst_%'] = result.loc[fund_rows, 'worst'] / result.loc[fund_rows, 'no_null_columns']
    result.loc[fund_rows, 'better_worst_diff'] = result.loc[fund_rows, 'better_%'] - result.loc[fund_rows, 'worst_%']
    
    # Calculate ranking distribution (10%, 20%, etc.)
    ranking_data = result[return_columns].rank(axis=0, ascending=False)
    data_size = len(ranking_data)
    size_range = data_size / 10
    
    # Calculate percentile buckets
    for i in range(1, 11):
        lower_bound = size_range * (i - 1)
        upper_bound = size_range * i
        if i == 10:
            bucket_name = 'worse_10%'
        else:
            bucket_name = f'{i * 10}%'
        
        count_in_bucket = ((ranking_data >= lower_bound) & (ranking_data < upper_bound)).sum(axis=1)
        result.loc[fund_rows, bucket_name] = count_in_bucket[fund_rows]
    
    # Return only fund rows with comparison metrics
    fund_comparison = result[fund_rows]
    comparison_columns = ['total_columns', 'no_null_columns', 'better', 'worst', 'better_%', 'worst_%', 
                         'better_worst_diff', '10%', '20%', '30%', '40%', '50%', '60%', '70%', '80%', '90%', 'worse_10%']
    
    return fund_comparison[comparison_columns]


def get_index_highest_lowest(index_returns: pd.DataFrame) -> pd.DataFrame:
    """
    Get highest and lowest returns from the three indexes for each period.
    
    Args:
        index_returns: DataFrame with index returns
    
    Returns:
        DataFrame with highest and lowest returns per period
    """
    return_columns = [col for col in index_returns.columns if col.startswith("Total Return")]
    
    highest_lowest = pd.DataFrame({
        'Highest Index Return': index_returns[return_columns].max(axis=0),
        'Lowest Index Return': index_returns[return_columns].min(axis=0),
        'Best Performing Index': index_returns[return_columns].idxmax(axis=0),
        'Worst Performing Index': index_returns[return_columns].idxmin(axis=0)
    })
    
    return highest_lowest.T


# Morningstar return periods to match
MORNINGSTAR_PERIODS = [
    "1W", "1M", "2M", "QTD", "3M", "6M", "9M", "YTD",
    "1Y", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y", "15Y", "20Y"
]


if __name__ == "__main__":
    # Test the module
    print("Testing index benchmark module...")
    
    # Calculate index returns for all periods
    index_returns = calculate_index_returns(MORNINGSTAR_PERIODS)
    print("\nIndex Returns:")
    print(index_returns)
    
    # Get highest/lowest
    highest_lowest = get_index_highest_lowest(index_returns)
    print("\nHighest/Lowest Index Returns:")
    print(highest_lowest)
