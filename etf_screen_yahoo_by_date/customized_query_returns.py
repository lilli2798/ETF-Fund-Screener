import yfinance as yf
import os
import re
import sys
import pandas as pd
from file_print import update_result_book_with_create_new_with_style
from colorama import Fore

from yahoo_get_top_return \
    import (calculate_up_to_today_return_yearly_rate, \
            calculate_yearly_rate_change, calculate_up_to_today_return_monthly_rate,
            calculate_up_to_today_return_weekly_rate, \
            calculate_monthly_rate_change, calculate_weekly_rate_change, \
            calculate_better_than_best)

# style for the console display
BOLD: str = '\033[1m'  # ANSI escape sequence for bold
END = '\033[0m'  # Reset formatting
RED = Fore.RED
BLUE = Fore.BLUE
INDENT = "    "  # Define your indent string
working_dir = ''
INDEXES = ["^IXIC", "^DJI", "^GSPC"]


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def processing_yahoo_week_return(df, filtered_df, result_file, sheet_sub_name):
    df = df.set_index('Ticker')
    df = df[~df.index.isna()]
    total_today_return_data = calculate_up_to_today_return_weekly_rate(filtered_df).dropna()
    total_better_than_best = calculate_better_than_best(total_today_return_data).dropna()
    total_return_data = pd.concat([df, total_today_return_data, total_better_than_best], axis=1)
    total_sheet_name = "Total-" + sheet_sub_name + "-overview"
    update_result_book_with_create_new_with_style(total_return_data, result_file, total_sheet_name)

    ly_return_data = calculate_weekly_rate_change(filtered_df)
    ly_better_than_best = calculate_better_than_best(ly_return_data)
    ly_high_low_data = pd.concat([df, ly_return_data, ly_better_than_best], axis=1)
    ly_sheet_name = sheet_sub_name + "-overview"
    update_result_book_with_create_new_with_style(ly_high_low_data, result_file, ly_sheet_name)


def processing_yahoo_month_return(df, filtered_df, result_file, sheet_sub_name):
    df = df.set_index('Ticker')
    df = df[~df.index.isna()]
    total_today_return_data = calculate_up_to_today_return_monthly_rate(filtered_df).dropna()
    total_better_than_best = calculate_better_than_best(total_today_return_data).dropna()
    total_return_data = pd.concat([df, total_today_return_data, total_better_than_best], axis=1)
    total_sheet_name = "Total-" + sheet_sub_name + "-overview"
    update_result_book_with_create_new_with_style(total_return_data, result_file, total_sheet_name)

    ly_return_data = calculate_monthly_rate_change(filtered_df)
    ly_better_than_best = calculate_better_than_best(ly_return_data)
    ly_high_low_data = pd.concat([df, ly_return_data, ly_better_than_best], axis=1)
    ly_sheet_name = sheet_sub_name + "-overview"
    update_result_book_with_create_new_with_style(ly_high_low_data, result_file, ly_sheet_name)


def processing_yahoo_year_return(df, yahoo_df, result_file, choice):
    df = df.set_index('Ticker')
    df = df[~df.index.isna()]
    total_today_return_data = calculate_up_to_today_return_yearly_rate(yahoo_df).dropna()
    total_better_than_best = calculate_better_than_best(total_today_return_data).dropna()
    total_return_data = pd.concat([df, total_today_return_data, total_better_than_best], axis=1)
    total_sheet_name = "Total-" + choice + "-overview"
    update_result_book_with_create_new_with_style(total_return_data, result_file, total_sheet_name)

    ly_return_data = calculate_yearly_rate_change(yahoo_df)
    ly_better_than_best = calculate_better_than_best(ly_return_data)
    ly_high_low_data = pd.concat([df, ly_return_data, ly_better_than_best], axis=1)
    ly_sheet_name = choice + "-overview"
    update_result_book_with_create_new_with_style(ly_high_low_data, result_file, ly_sheet_name)


def process_period_choice(df, yahoo_df, result_file, period_type, processing_func):
    """Generic function handle year/month/week processing."""
    num_input = int(input(f"{BOLD}{RED} Please number of {period_type} from today: {END}"))
    last_date = yahoo_df.index[-1]
    
    if period_type == "year":
        offset = pd.DateOffset(years=num_input)
        filtered_df = yahoo_df  # Year uses full yahoo_df
    elif period_type == "month":
        offset = pd.DateOffset(months=num_input)
        filtered_df = yahoo_df.loc[last_date - offset:last_date]
    elif period_type == "week":
        offset = pd.DateOffset(weeks=num_input)
        filtered_df = yahoo_df.loc[last_date - offset:last_date]
    else:
        raise ValueError(f"Invalid period_type: {period_type}. Must be 'year', 'month', or 'week'.")
    
    sheet_sub_name = str(num_input) + '-' + period_type
    processing_func(df, filtered_df, result_file, sheet_sub_name)


def process_yahoo_data(df, yahoo_df, result_file):
    print(f"{INDENT} year: Calculate yearly return results")
    print(f"{INDENT} month: Calculate monthly return results")
    print(f"{INDENT} week: Calculate weekly return results")
    print(f"{INDENT} year_date: Calculate year up to date result")
    print(f"{INDENT} 0. Main  ")
    print(f"{INDENT} 99. Exit ")
    print(f"{INDENT} 0. Main menu ")
    choice_options = ["year", "month", "week", "exit", "0", "99"]

    current_choice = input(f"{BOLD}{RED}Choose from ({', '.join(choice_options)}): {END}").lower()
    print(f"{INDENT} {BLUE} You have choose {current_choice}. {END}")
    if current_choice.strip() not in choice_options:
        print("Invalid choice. Please select from the available options.")
        process_yahoo_data(df, yahoo_df, result_file)
    print(f"{INDENT} {BLUE} You have choose {current_choice}. {END}")
    
    if current_choice.strip() == "year":
        process_period_choice(df, yahoo_df, result_file, "year", processing_yahoo_year_return)
        process_yahoo_data(df, yahoo_df, result_file)
    elif current_choice.strip() == "month":
        process_period_choice(df, yahoo_df, result_file, "month", processing_yahoo_month_return)
        process_yahoo_data(df, yahoo_df, result_file)
    elif current_choice.strip() == "week":
        process_period_choice(df, yahoo_df, result_file, "week", processing_yahoo_week_return)
        process_yahoo_data(df, yahoo_df, result_file)
    elif current_choice.strip() == "0":
        main_menu()
    elif current_choice.strip() == "99":
        print("Exiting...")
        exit()
    # else will return-back to current function


def get_yahoo_data(symbols, starting_date, ending_date):
    all_adj_close = []
    for batch in chunks(symbols, 200):
        data = yf.download(
            tickers=batch,
            start=starting_date,
            end=ending_date,
            interval="1d",
            auto_adjust=False,
            threads=True,
        )["Adj Close"]
        all_adj_close.append(data)
    return pd.concat(all_adj_close, axis=1)

def processing_by_sheet_name(df, result_file, sheet_name, boolean):
    starting_date_message = f'{BOLD}{RED}Enter STARTING date in 2001-02-01 format:  {END}'
    starting_date = input(starting_date_message)
    ending_date_message = f"{BOLD}{RED}Enter ENDING date in 2001-02-01 format:  {END}"
    ending_date = input(ending_date_message)
    symbols = df['Ticker'].values.tolist()
    symbols.extend(INDEXES)
    symbols = [str(ticker) for ticker in symbols]
    yahoo_df = get_yahoo_data(symbols, starting_date, ending_date)
    # write the yahoo data to the file
    # update_result_book_with_create_new(yahoo_df, result_file, 'yahoo-return')
    process_yahoo_data(df, yahoo_df, result_file)

def get_ticker_from_txt_file(filename):
    # Read the file line by line (assuming each row has a single ticker)
    with open(filename, 'r') as f:
        tickers = f.readlines()
    # Strip any trailing whitespace (like newline characters) from each ticker
    tickers = [ticker.strip() for ticker in tickers]

    # Create a DataFrame with the list of tickers as a column named 'ticker'
    df = pd.DataFrame({'Ticker': tickers})
    df.set_index('Ticker')
    return df

def get_data_from_file_sheet(file_name, sheet_name, max_retries=2):
    attempts = 0
    while attempts < max_retries:
        try:
            return pd.read_excel(file_name, sheet_name=sheet_name, engine='openpyxl')
        except PermissionError as e:
            attempts += 1
            print(f"Attempt {attempts}/{max_retries}: File is locked. {e}")
            input("Please close the file and press Enter to retry...\n")
        except FileNotFoundError as e:
            print(f"File not found: {e}")
            sys.exit(1)
    print("Too many failed attempts. Exiting.")
    sys.exit(1)

def main_menu():
    message = f"{BOLD}{RED}Please provide working directory: {END}"
    working_directory = input(message)
    message_file = f"{BOLD}{RED}Please provide file name: {END}"
    working_file = input(message_file)
    working_file_name = os.path.join(working_directory, working_file)
    
    if working_file_name.endswith('.txt'):
        print(f"You are working on a txt file: {working_file_name}")
        df = get_ticker_from_txt_file(working_file_name)
        result_file = working_file_name.replace('.txt', '.xlsx')
        sheet_name = "Recorder"
        processing_by_sheet_name(df, result_file, sheet_name, False)
    else:
        message_sheet = f"{BOLD}{RED}Please provide sheet name: {END}"
        sheet_name = input(message_sheet)
        print(f"You are working on an xlsx file: {working_file_name} on sheet: {sheet_name}")
        df = get_data_from_file_sheet(working_file_name, sheet_name)
        processing_by_sheet_name(df, working_file_name, sheet_name, True)


if __name__ == "__main__":
    main_menu()