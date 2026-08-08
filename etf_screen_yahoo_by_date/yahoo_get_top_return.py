from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf

from file_print import update_result_book_with_create_new_with_style
# Get the current date
current_date = datetime.now()

# Calculate the date 20 years ago
twenty_years_ago = current_date - timedelta(days=365.25 * 20)
three_years_ago = current_date - timedelta(days=365.25 * 3)

# Format and display the result
start_date = twenty_years_ago.strftime("%Y-%m-%d")
today = datetime.today().strftime("%Y-%m-%d")
INDEXES = ["^IXIC", "^DJI", "^GSPC"]
# INDEXES = ["^IXIC", "^DJI", "^GSPC", "^RUT", "^NDX", "^OEX"]
three_years_ago_today = three_years_ago.strftime("%Y-%m-%d")


def download_yahoo_data(table_data, overview_output_file):
    if len(table_data) > 0:
        print('>>>>>>>> processing over view :' + str(len(table_data)))
        symbols = table_data.index.astype(str).tolist()
        symbols.extend(INDEXES)
        yahoo_df = yf.download(symbols, start=start_date, end=today, threads=3)['Adj Close']
        # yahoo_data_file_name = overview_output_file.replace('.xlsx', '-yahoo.xlsx')
        # filter_write(yahoo_data_file_name, 'yahoo-return', yahoo_df)

        highest_lowest_data = get_highest_lowest(symbols)
        # get total returns
        total_up_today_return_data = calculate_up_to_today_return_yearly_rate(yahoo_df)
        total_better_than_best = calculate_better_than_best(total_up_today_return_data)
        total_return_data = pd.concat(
            [table_data, highest_lowest_data, total_up_today_return_data, total_better_than_best], axis=1)
        total_return_data.index.name = 'Ticker'
        update_result_book_with_create_new_with_style(total_return_data, overview_output_file, 'Total-today-overview')

        # get yearly return
        yearly_return_data = calculate_yearly_rate_change(yahoo_df)
        yearly_better_than_best = calculate_better_than_best(yearly_return_data)
        # get highest and lowest return

        yearly_high_low_data = pd.concat([table_data, highest_lowest_data, yearly_return_data, yearly_better_than_best],
                                         axis=1)
        yearly_high_low_data.index.name = 'Ticker'
        update_result_book_with_create_new_with_style(yearly_high_low_data, overview_output_file, 'Yearly-overview')
        return yearly_high_low_data
    return None


def calculate_better_than_best(returns):
    date_column = returns.columns
    # Count total columns in the DataFrame
    returns['total_columns'] = returns.shape[1]
    # Count non-null columns for each row
    returns['no_null_columns'] = returns.count(axis=1)
    # get all three index value and set the max and min, larger means better return
    index_df = returns.loc[INDEXES]
    # compare the return is better
    max_values = index_df.max(axis=0)
    returns.loc['max'] = max_values
    min_values = index_df.min(axis=0)
    returns.loc['min'] = min_values

    all_indexes_df = returns.index.tolist()
    # Compare differences based on different indexes
    better_differences = returns.loc[all_indexes_df].values > returns.loc['max'].values
    returns['better'] = better_differences.sum(axis=1)

    worse_differences = returns.loc[all_indexes_df].values < returns.loc['min'].values
    returns['worst'] = worse_differences.sum(axis=1)
    # returns['worst'] = returns.apply(subtract_one, axis=1)
    returns['better_%'] = returns['better'] / returns['no_null_columns']
    returns['worst_%'] = returns['worst'] / returns['no_null_columns']
    returns['better_worst_diff'] = returns['better_%'] - returns['worst_%']

    # Since first column has no rate of change, so need remove it from lines
    ranking_data = returns.filter(date_column)
    # Delete the dataframe to release memory
    # need to merge returns with ranking

    # Trigger garbage collection to release memory
    # gc.collect()

    for line in date_column:
        calculate_and_add_rank(ranking_data, line)
    ranked_data = ranking_data.filter(like='rank')
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

    # Count elements in each column within the specified range
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
    print("&&&&& 3333  check if duplicated &&&&")
    print(ranked_data.index.duplicated().any())
    return ranked_data


def calculate_yearly_rate_change(yahoo_df):
    # convert index to derangement type for grouping process
    yahoo_df.index = pd.to_datetime(yahoo_df.index)
    df = yahoo_df.groupby(yahoo_df.index.year).head(1)

    # Calculate percentage changes for each value column
    pct_change_df = df.pct_change()
    df = pct_change_df.T.dropna(axis=1, how='all')
    df.index.name = "Ticker"
    df.columns = pd.to_datetime(df.columns)
    df.columns = [f"Yearly_{col.year - 1}" for col in df.columns]
    return df


def calculate_rolling_returns_from_today(yahoo_df, years=[1, 2, 3, 5, 10]):
    """Calculate rolling returns from today for specified year periods."""
    yahoo_df.index = pd.to_datetime(yahoo_df.index)
    today = yahoo_df.index.max()
    
    returns_data = {}
    
    for year in years:
        start_date = today - timedelta(days=365.25 * year)
        # Get data at start date and today
        start_price = yahoo_df.loc[yahoo_df.index >= start_date].iloc[0]
        end_price = yahoo_df.loc[today]
        
        # Calculate return
        period_return = (end_price - start_price) / start_price
        returns_data[f"{year}-Year"] = period_return
    
    df = pd.DataFrame(returns_data)
    df.index.name = "Ticker"
    return df


def _calculate_up_to_today_return(yahoo_df, grouped_data, check_duplicates=False):
    end_date = yahoo_df.tail(1)
    changes = []
    for index, row in grouped_data.iterrows():
        print(f"Index: {index}, Row: {row}")
        change = (end_date - row) / row
        changes.append(change)

    total_return = pd.concat(changes, axis=0)
    total_return.index = 'total-' + grouped_data.index.strftime('%m/%d/%Y')
    if check_duplicates:
        print("&&&&& 2222  check if duplicated &&&&")
        print(total_return.index.duplicated().any())
    total_return = total_return.T.reset_index().rename(columns={'index': 'Ticker'}).set_index('Ticker')
    return total_return


def calculate_up_to_today_return_yearly_rate(yahoo_df):
    yahoo_df.index = pd.to_datetime(yahoo_df.index)
    yearly_data = yahoo_df.groupby(yahoo_df.index.year).head(1)
    return _calculate_up_to_today_return(yahoo_df, yearly_data, check_duplicates=True)


def calculate_monthly_rate_change(filtered_df):
    filtered_df.index = pd.to_datetime(filtered_df.index)
    first_day_of_month = filtered_df.groupby(filtered_df.index.month).head(1)
    # Calculate monthly returns
    monthly_return = first_day_of_month.pct_change()
    monthly_return.index = 'monthly-' + monthly_return.index.strftime('%m/%d/%Y')
    # Transpose the DataFrame, reset the index, and add a new index name
    monthly_return = monthly_return.T.reset_index().rename(columns={'index': 'Ticker'}).set_index('Ticker')
    return monthly_return


def calculate_up_to_today_return_monthly_rate(yahoo_df):
    yahoo_df.index = pd.to_datetime(yahoo_df.index)
    monthly_data = yahoo_df.groupby(yahoo_df.index.month).head(1)
    return _calculate_up_to_today_return(yahoo_df, monthly_data)


def calculate_weekly_rate_change(filtered_df):
    filtered_df.index = pd.to_datetime(filtered_df.index)
    first_day_of_week = filtered_df.groupby(filtered_df.index.isocalendar().week).head(1)
    # Calculate monthly returns
    weekly_return = first_day_of_week.pct_change()
    weekly_return.index = 'weekly-' + weekly_return.index.strftime('%m/%d/%Y')
    # Transpose the DataFrame, reset the index, and add a new index name
    weekly_return = weekly_return.T.reset_index().rename(columns={'index': 'Ticker'}).set_index('Ticker')
    return weekly_return


def calculate_up_to_today_return_weekly_rate(yahoo_df):
    yahoo_df.index = pd.to_datetime(yahoo_df.index)
    first_day_of_week = yahoo_df.groupby(yahoo_df.index.isocalendar().week).head(1)
    return _calculate_up_to_today_return(yahoo_df, first_day_of_week)


def get_highest_lowest(symbols):
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
            # Retrieve data using yfinance
            current_data = yf.download(symbol, start=three_years_ago_today, end=today, threads=3)
            # Calculate highest and lowest values
            highest_value = current_data['High'].max()
            lowest_value = current_data['Low'].min()
            highest_date = current_data[current_data['High'] == highest_value].index[0]
            highest_date = highest_date.strftime("%Y-%m-%d")
            lowest_date = current_data[current_data['Low'] == lowest_value].index[0]
            lowest_date = lowest_date.strftime("%Y-%m-%d")

            ticker = yf.Ticker(symbol)
            latest_data = ticker.history(period="1d")

            # Access the adjusted closing price for today
            adj_close_price = latest_data['Close'].iloc[0]
            today_price = current_data['Adj Close'][0].iloc[0]
            change_in_high_low = (highest_value - lowest_value)/highest_value
            change_in_today_high = (today_price - highest_value)/highest_value
            change_in_today_low = (today_price - lowest_value)/today_price

            # Append data to lists
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
    print(f"Error processing {error_symbols} with : {e}")

    # Create a DataFrame
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
    if column_name not in dataframe.columns:
        print(f"Column '{column_name}' not found in the DataFrame.")
        return

    ranking_column = f'{column_name}_rank'
    dataframe[ranking_column] = dataframe[column_name].rank(ascending=False, method='dense')
    return dataframe
