"""Pull Yahoo Finance price history for screened ETFs and score them against market indexes.

Entry point is ``download_yahoo_data``: it downloads adjusted close prices, computes
3-year high/low stats, total and calendar-year returns, compares each ticker with the
benchmark indexes in ``INDEXES``, and writes the results to two sheets of an Excel workbook.
"""
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

from file_print import update_result_book_with_create_new_with_style

current_date = datetime.now()

# 20-year window for return history; 3-year window for the recent high/low analysis.
twenty_years_ago = current_date - timedelta(days=365.25 * 20)
three_years_ago = current_date - timedelta(days=365.25 * 3)

# yfinance expects dates as "YYYY-MM-DD" strings.
start_date = twenty_years_ago.strftime("%Y-%m-%d")
today = datetime.today().strftime("%Y-%m-%d")
# Benchmark indexes: NASDAQ Composite, Dow Jones Industrial Average, S&P 500.
INDEXES = ["^IXIC", "^DJI", "^GSPC"]
# INDEXES = ["^IXIC", "^DJI", "^GSPC", "^RUT", "^NDX", "^OEX"]
three_years_ago_today = three_years_ago.strftime("%Y-%m-%d")


def download_yahoo_data(table_data, overview_output_file):
    """Download price history for the screened ETFs and write return overviews to Excel.

    Args:
        table_data: DataFrame indexed by ticker (the screener output).
        overview_output_file: Path of the .xlsx workbook to write.

    Writes two sheets:
        'Total-today-overview': return from the first trading day of each year up to today.
        'Yearly-overview': calendar-year returns.

    Returns:
        The yearly overview DataFrame, or None if ``table_data`` is empty.
    """
    if len(table_data) > 0:
        print('>>>>>>>> processing over view :' + str(len(table_data)))
        # Download the ETFs together with the benchmark indexes so they share the same date index.
        symbols = table_data.index.astype(str).tolist()
        symbols.extend(INDEXES)
        # auto_adjust=False keeps the 'Adj Close' column (newer yfinance adjusts by default and drops it).
        yahoo_df = yf.download(symbols, start=start_date, end=today, threads=3, auto_adjust=False)['Adj Close']
        # Uncomment to dump the raw Yahoo prices for debugging or manual review.
        # yahoo_data_file_name = overview_output_file.replace('.xlsx', '-yahoo.xlsx')
        # filter_write(yahoo_data_file_name, 'yahoo-return', yahoo_df)

        highest_lowest_data = get_highest_lowest(symbols)

        # Total return from the first trading day of each year up to the latest date.
        total_up_today_return_data = calculate_up_to_today_return_yearly_rate(yahoo_df)
        total_better_than_best = calculate_better_than_best(total_up_today_return_data)
        total_return_data = pd.concat(
            [table_data, highest_lowest_data, total_up_today_return_data, total_better_than_best], axis=1)
        total_return_data.index.name = 'Ticker'
        update_result_book_with_create_new_with_style(total_return_data, overview_output_file, 'Total-today-overview')

        # Calendar-year returns (first trading day of one year to the first trading day of the next).
        yearly_return_data = calculate_yearly_rate_change(yahoo_df)
        yearly_better_than_best = calculate_better_than_best(yearly_return_data)

        yearly_high_low_data = pd.concat([table_data, highest_lowest_data, yearly_return_data, yearly_better_than_best],
                                         axis=1)
        yearly_high_low_data.index.name = 'Ticker'
        update_result_book_with_create_new_with_style(yearly_high_low_data, overview_output_file, 'Yearly-overview')
        return yearly_high_low_data
    return None


def calculate_better_than_best(returns):
    """Score each ticker against the benchmark indexes and bucket its ranks into deciles.

    ``returns`` has one row per ticker (indexes included) and one column per period.

    Side effect: ``returns`` is modified in place. It gains 'max'/'min' rows (best and worst
    index return per period) and these columns:
        total_columns / no_null_columns: number of periods / periods with data.
        better / worst: periods where the ticker beat the best index / trailed the worst index.
        better_% / worst_%: those counts divided by no_null_columns.
        better_worst_diff: better_% - worst_%.

    Returns:
        A new DataFrame with a '<period>_rank' column per period (1 = highest return) and
        decile counts '10%' ... '90%', 'worse_10%': how many periods the ticker ranked in each
        tenth of the universe.
    """
    # Keep the original period columns before helper columns are added.
    date_column = returns.columns
    returns['total_columns'] = len(date_column)
    # Count periods with data so tickers with shorter history are not penalized.
    returns['no_null_columns'] = returns[date_column].count(axis=1)
    # The benchmark band for each period: best ('max') and worst ('min') index return.
    index_df = returns.loc[INDEXES, date_column]
    max_values = index_df.max(axis=0)
    returns.loc['max', date_column] = max_values
    min_values = index_df.min(axis=0)
    returns.loc['min', date_column] = min_values

    # Count, per ticker, the periods above the best index and below the worst index.
    period_returns = returns[date_column].values
    better_differences = period_returns > returns.loc['max', date_column].values
    returns['better'] = better_differences.sum(axis=1)

    worse_differences = period_returns < returns.loc['min', date_column].values
    returns['worst'] = worse_differences.sum(axis=1)
    # returns['worst'] = returns.apply(subtract_one, axis=1)
    returns['better_%'] = returns['better'] / returns['no_null_columns']
    returns['worst_%'] = returns['worst'] / returns['no_null_columns']
    returns['better_worst_diff'] = returns['better_%'] - returns['worst_%']

    # Rank only the original period columns; the helper columns above are left out.
    # The 'max'/'min' rows are still present and get ranked like any ticker.
    ranking_data = returns.filter(date_column)

    # Trigger garbage collection to release memory
    # gc.collect()

    # Add a '<period>_rank' column to ranking_data for every period.
    for line in date_column:
        calculate_and_add_rank(ranking_data, line)
    ranked_data = ranking_data.filter(like='rank')

    # Rank boundaries for each tenth of the universe (size_range = 10% of the rows).
    data_size = len(ranked_data)
    size_range = data_size / 10
    top_1_10 = size_range
    top_2_10 = size_range * 2
    top_3_10 = size_range * 3
    top_4_10 = size_range * 4
    top_5_10 = size_range * 5
    top_6_10 = size_range * 6
    top_7_10 = size_range * 7
    top_8_10 = size_range * 8
    top_9_10 = size_range * 9
    top_10_10 = size_range * 10

    # For each ticker, count how many periods its rank fell in each decile.
    # '10%' is the top tenth (best returns), 'worse_10%' is the bottom tenth.
    count_within_rang_10 = ranked_data.map(lambda x: 1 if 0 <= x < top_1_10 else 0)
    ranked_data['10%'] = count_within_rang_10.sum(axis=1)
    count_within_rang_20 = ranked_data.map(lambda x: 1 if top_1_10 <= x < top_2_10 else 0)
    ranked_data['20%'] = count_within_rang_20.sum(axis=1)
    count_within_rang_30 = ranked_data.map(lambda x: 1 if top_2_10 <= x < top_3_10 else 0)
    ranked_data['30%'] = count_within_rang_30.sum(axis=1)
    count_within_rang_40 = ranked_data.map(lambda x: 1 if top_3_10 <= x < top_4_10 else 0)
    ranked_data['40%'] = count_within_rang_40.sum(axis=1)
    count_within_rang_50 = ranked_data.map(lambda x: 1 if top_4_10 <= x < top_5_10 else 0)
    ranked_data['50%'] = count_within_rang_50.sum(axis=1)
    count_within_rang_60 = ranked_data.map(lambda x: 1 if top_5_10 <= x < top_6_10 else 0)
    ranked_data['60%'] = count_within_rang_60.sum(axis=1)
    count_within_rang_70 = ranked_data.map(lambda x: 1 if top_6_10 <= x < top_7_10 else 0)
    ranked_data['70%'] = count_within_rang_70.sum(axis=1)
    count_within_rang_80 = ranked_data.map(lambda x: 1 if top_7_10 <= x < top_8_10 else 0)
    ranked_data['80%'] = count_within_rang_80.sum(axis=1)
    count_within_rang_90 = ranked_data.map(lambda x: 1 if top_8_10 <= x < top_9_10 else 0)
    ranked_data['90%'] = count_within_rang_90.sum(axis=1)
    count_within_rang_100 = ranked_data.map(lambda x: 1 if top_9_10 <= x < top_10_10 else 0).copy()
    ranked_data['worse_10%'] = count_within_rang_100.sum(axis=1)
    # Debug: duplicate tickers would break the concat in download_yahoo_data.
    print("&&&&& 3333  check if duplicated &&&&")
    print(ranked_data.index.duplicated().any())
    return ranked_data


def calculate_yearly_rate_change(yahoo_df):
    """Return each ticker's calendar-year returns, one 'Yearly_<year>' column per year.

    The return for year Y is measured from the first trading day of Y to the first
    trading day of Y + 1.
    """
    # Convert the index to datetime so rows can be grouped by year.
    yahoo_df.index = pd.to_datetime(yahoo_df.index)
    # Keep the first trading day of each year.
    df = yahoo_df.groupby(yahoo_df.index.year).head(1)

    # Change from one year's first trading day to the next.
    pct_change_df = df.pct_change()
    # Transpose to one row per ticker; drop the first year, which has no prior value.
    df = pct_change_df.T.dropna(axis=1, how='all')
    df.index.name = "Ticker"
    df.columns = pd.to_datetime(df.columns)
    # The change recorded on Jan of year Y covers year Y - 1, so label it with Y - 1.
    df.columns = [f"Yearly_{col.year - 1}" for col in df.columns]
    return df


def calculate_rolling_returns_from_today(yahoo_df, years=[1, 2, 3, 5, 10]):
    """Return each ticker's trailing return over the last N years, one 'N-Year' column per period."""
    yahoo_df.index = pd.to_datetime(yahoo_df.index)
    today = yahoo_df.index.max()

    returns_data = {}

    for year in years:
        start_date = today - timedelta(days=365.25 * year)
        # Price on the first trading day on or after the start date, and on the latest date.
        start_price = yahoo_df.loc[yahoo_df.index >= start_date].iloc[0]
        end_price = yahoo_df.loc[today]

        period_return = (end_price - start_price) / start_price
        returns_data[f"{year}-Year"] = period_return

    df = pd.DataFrame(returns_data)
    df.index.name = "Ticker"
    return df


def _calculate_up_to_today_return(yahoo_df, grouped_data, check_duplicates=False):
    """Return each ticker's return from every date in ``grouped_data`` up to the latest price.

    The result has one row per ticker and one 'total-MM/DD/YYYY' column per start date.
    """
    # Latest row of prices (a one-row DataFrame).
    end_date = yahoo_df.tail(1)
    changes = []
    for index, row in grouped_data.iterrows():
        print(f"Index: {index}, Row: {row}")
        # Return from this start date to the latest date, for every ticker.
        change = (end_date - row) / row
        changes.append(change)

    # One row per start date; label each row by its start date.
    total_return = pd.concat(changes, axis=0)
    total_return.index = 'total-' + grouped_data.index.strftime('%m/%d/%Y')
    if check_duplicates:
        print("&&&&& 2222  check if duplicated &&&&")
        print(total_return.index.duplicated().any())
    # Transpose so tickers become rows, indexed by 'Ticker'.
    total_return = total_return.T.reset_index().rename(columns={'index': 'Ticker'}).set_index('Ticker')
    return total_return


def calculate_up_to_today_return_yearly_rate(yahoo_df):
    """Return each ticker's return from the first trading day of every year up to the latest date."""
    yahoo_df.index = pd.to_datetime(yahoo_df.index)
    yearly_data = yahoo_df.groupby(yahoo_df.index.year).head(1)
    return _calculate_up_to_today_return(yahoo_df, yearly_data, check_duplicates=True)


def calculate_monthly_rate_change(filtered_df):
    """Return month-over-month returns, one 'monthly-MM/DD/YYYY' column per month."""
    filtered_df.index = pd.to_datetime(filtered_df.index)
    # Group by calendar month (year + month) so multi-year data keeps every month.
    first_day_of_month = filtered_df.groupby(filtered_df.index.to_period('M')).head(1)
    monthly_return = first_day_of_month.pct_change()
    monthly_return.index = 'monthly-' + monthly_return.index.strftime('%m/%d/%Y')
    # Transpose so tickers become rows, indexed by 'Ticker'.
    monthly_return = monthly_return.T.reset_index().rename(columns={'index': 'Ticker'}).set_index('Ticker')
    return monthly_return


def calculate_up_to_today_return_monthly_rate(yahoo_df):
    """Return each ticker's return from the first trading day of each month up to the latest date."""
    yahoo_df.index = pd.to_datetime(yahoo_df.index)
    monthly_data = yahoo_df.groupby(yahoo_df.index.to_period('M')).head(1)
    return _calculate_up_to_today_return(yahoo_df, monthly_data)


def calculate_weekly_rate_change(filtered_df):
    """Return week-over-week returns, one 'weekly-MM/DD/YYYY' column per week."""
    filtered_df.index = pd.to_datetime(filtered_df.index)
    # Group by calendar week (Monday-Sunday, year included) so multi-year data keeps every week.
    first_day_of_week = filtered_df.groupby(filtered_df.index.to_period('W')).head(1)
    weekly_return = first_day_of_week.pct_change()
    weekly_return.index = 'weekly-' + weekly_return.index.strftime('%m/%d/%Y')
    # Transpose so tickers become rows, indexed by 'Ticker'.
    weekly_return = weekly_return.T.reset_index().rename(columns={'index': 'Ticker'}).set_index('Ticker')
    return weekly_return


def calculate_up_to_today_return_weekly_rate(yahoo_df):
    """Return each ticker's return from the first trading day of each week up to the latest date."""
    yahoo_df.index = pd.to_datetime(yahoo_df.index)
    first_day_of_week = yahoo_df.groupby(yahoo_df.index.to_period('W')).head(1)
    return _calculate_up_to_today_return(yahoo_df, first_day_of_week)


def get_highest_lowest(symbols):
    """Return 3-year high/low prices and dates for each symbol, plus how far today's price is from them.

    Symbols that fail to download are skipped. The result is indexed by 'Ticker'.
    """
    symbol_list = []
    highest_prices = []
    lowest_prices = []
    error_symbols = []
    highest_dates = []
    lowest_dates = []
    today_prices = []
    change_in_highs_lows = []
    change_in_today_highs = []
    change_in_today_lows = []
    for symbol in symbols:
        try:
            # Daily prices for the last 3 years. Unadjusted prices keep High, Low and Close on
            # the same basis; multi_level_index=False gives flat columns for a single ticker.
            current_data = yf.download(symbol, start=three_years_ago_today, end=today, threads=3,
                                       auto_adjust=False, multi_level_index=False, progress=False)
            if current_data.empty:
                raise ValueError("no price data returned")
            # Highest high / lowest low in the window, and the first date each was reached.
            highest_value = current_data['High'].max()
            lowest_value = current_data['Low'].min()
            highest_date = current_data['High'].idxmax().strftime("%Y-%m-%d")
            lowest_date = current_data['Low'].idxmin().strftime("%Y-%m-%d")

            # Most recent close in the window (the last completed trading day).
            today_price = current_data['Close'].iloc[-1]
            # Drawdown from high to low, and today's price relative to the high and the low.
            change_in_high_low = (highest_value - lowest_value)/highest_value
            change_in_today_high = (today_price - highest_value)/highest_value
            change_in_today_low = (today_price - lowest_value)/lowest_value

            symbol_list.append(symbol)
            highest_prices.append(highest_value)
            lowest_prices.append(lowest_value)
            highest_dates.append(highest_date)
            lowest_dates.append(lowest_date)
            today_prices.append(today_price)
            change_in_highs_lows.append(change_in_high_low)
            change_in_today_highs.append(change_in_today_high)
            change_in_today_lows.append(change_in_today_low)

        except Exception as e:
            error_symbols.append(symbol)
            print(f"Error processing {symbol}: {e}")
    if error_symbols:
        print(f"Skipped {len(error_symbols)} symbol(s): {error_symbols}")

    data = {
        'Ticker': symbol_list,
        'Highest Price 3Yr': highest_prices,
        'Highest Date': highest_dates,
        'Lowest Price 3Yr': lowest_prices,
        'Lowest Date': lowest_dates,
        'Today Price': today_prices,
        'Change High-Low': change_in_highs_lows,
        'Change Today-High': change_in_today_highs,
        'Change Today-Low': change_in_today_lows
    }
    result_df = pd.DataFrame(data)
    result_df.set_index('Ticker', inplace=True)

    return result_df


def calculate_and_add_rank(dataframe, column_name):
    """Add a '<column_name>_rank' column to ``dataframe`` in place (1 = highest value, dense ranking)."""
    if column_name not in dataframe.columns:
        print(f"Column '{column_name}' not found in the DataFrame.")
        return

    ranking_column = f'{column_name}_rank'
    dataframe[ranking_column] = dataframe[column_name].rank(ascending=False, method='dense')
    return dataframe
