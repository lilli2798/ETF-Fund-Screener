import operator as ops
import ast
import pandas as pd
from utils.message_styles import BOLD, END, RED, BLUE
from utils.user_input_utils import input_with_default

from utils.file_print import update_result_book_with_create_new
from utils.load_data import get_df_by_dir

# # Define supported operators
ops = {
    ">": ops.gt,
    "<": ops.lt,
    ">=": ops.ge,
    "<=": ops.le,
    "==": ops.eq,
    "!=": ops.ne
}


def filter_df(df, condition_groups):
    """
    Filters a DataFrame based on grouped conditions with AND/OR logic.

    Parameters:
        df (pd.DataFrame): The input DataFrame.
        condition_groups (list or dict): A single group (dict) or list of groups specifying "logic" and "conditions".

    Returns:
        pd.DataFrame: Filtered DataFrame based on the given grouped conditions.
    """
    # If a single dictionary is passed, convert it to a list of one group
    if isinstance(condition_groups, dict):
        condition_groups = [condition_groups]

    # Initialize the overall filter (all False to start)
    overall_filter = pd.Series(False, index=df.index)

    # Iterate through groups of conditions
    for group in condition_groups:
        logic = group["logic"]  # AND / OR
        conditions = group["conditions"]  # List of conditions

        # Initialize group filter
        if logic == "AND":
            group_filter = pd.Series(True, index=df.index)
        elif logic == "OR":
            group_filter = pd.Series(False, index=df.index)
        else:
            raise ValueError("Logic must be 'AND' or 'OR'.")

        # Apply conditions within the group
        for condition in conditions:
            col1, op, col2 = condition

            if col1 not in df.columns:
                print(f"Column '{col1}' not found in DataFrame.")
                continue
            # Check if col2 is a column or a fixed value
            if col2 in df.columns:  # Column-to-column comparison
                non_empty_mask = df[col1].notna() & df[col2].notna() & (df[col1] != '') & (df[col2] != '')
                condition_mask = non_empty_mask & ops[op](df[col1], df[col2])
            else:  # Column-to-value comparison
                non_empty_mask = df[col1].notna() & (df[col1] != '')
                condition_mask = non_empty_mask & ops[op](df[col1], col2)

            # Combine conditions in the group
            if logic == "AND":
                group_filter &= condition_mask
            elif logic == "OR":
                group_filter |= condition_mask

        # Combine group filter with the overall filter (use OR logic for groups)
        overall_filter |= group_filter

    # Return the filtered DataFrame
    return df[overall_filter]


# used to create a result tab name and search condition (query)
def dict_from_input_string():
    user_input = input("Please input search condition based on the example above, "
                       f"AND, OR, MIX,  Enter a {BOLD}{RED} DIST: {END}")
    try:
        # Convert string to dictionary safely
        result = ast.literal_eval(user_input)
        if isinstance(result, dict):
            return result
        else:
            print("Invalid input. Please enter a valid dictionary.")
            return None
    except (ValueError, SyntaxError):
        print("Invalid dictionary format.")
        return None


def get_results(df, working_file_name, working_sheet_name):
    print(f"{BOLD}{BLUE} 1 {END} for for continue.")
    print(f"{BOLD}{BLUE} 0 {END} for back to main.")
    print(f"{BOLD}{BLUE} 9 {END} for for exit. ")
    choice = input_with_default(f"{BOLD}{RED} default is 1 {END} for continue: ", "1")
    if choice == '1':
        try:
            print("Here are the column in the data set")
            for column_name in df.columns:
                print(column_name)
            result_sheet_name = input("Based on the column you selected to work with, "
                                      f"please provide a {BOLD}{RED} meaningful sheet name. {END} ")

            and_example = {"logic": "AND", "conditions": [
                ("1M Return Rank in Category", "<", 50), ("2M Return Rank in Category", "<", 50),
                ("20Y Return Rank in Category", "<", 50)]}
            print("Here is an example of AND logic ")
            print(and_example)

            or_example = {"logic": "OR", "conditions": [
                ("Asset Class", "==", "Miscellaneous"),
                ("Asset Class", "==", "International Equity")]}
            print("Here is an example of OR logic ")
            print(or_example)
            mix_example = [
                {"logic": "AND", "conditions": [
                    ("Fair Value", ">", "Last Price"), ("5-Star Price", ">", "Last Price"), ]},
                {"logic": "OR", "conditions": [
                    ("Return on Equity", ">", 15), ("Return on Invested Capital", ">", 10)]}
            ]
            print("Here is an example of MIX logic ")
            print(mix_example)
            search_conditions = dict_from_input_string()
            sub_df = filter_df(df, search_conditions)
            if sub_df is None or sub_df.empty:
                raise ValueError(f"There is not return result for the {working_sheet_name}")
            else:
                update_result_book_with_create_new(sub_df, working_file_name, result_sheet_name)

            print(f"{BOLD}{BLUE} 1 for whole data set {END}")
            print(f"{BOLD}{BLUE}2 for sub set that is from previous query. {END}")
            data_set_choice = input_with_default(f"{BOLD}{RED}1 {END} is the default", "1")
            if data_set_choice == "2":
                get_results(sub_df, working_file_name, working_sheet_name)
            else:
                get_results(df, working_file_name, working_sheet_name)
        except (ValueError, SyntaxError) as e:
            print(f"Catch in addon_query_search_funds with error ValueError : {e} {END}")
            get_results(df, working_file_name, working_sheet_name)
    elif choice == '0':
        print("Get back to main where you can reselect dir, file")
        main()
    elif choice == '9':
        print("Exiting the program...")
        exit()


def main():
    print("*" * 10 + "    Main Menu: All the work will be done in the same directory with yahoo return results   "
                     " Sheet name ends with week-overview is the weekly result. "
                     " Sheet name starts with Total is the total returns. " + "*" * 10)
    print(f"{BOLD}{BLUE}1. You will work on Yahoo results make sure you select correct sheet name correctly {END}")
    print(f"{BOLD}{BLUE}0: Main menu {END}")
    print(f"{BOLD}{BLUE}99. Exit {END}")
    choice = (input_with_default(f"{BOLD}{RED}Enter your choice: {END}", "1")).upper()
    if choice == "1":
        directory = input(f" {BOLD}{RED}Please Provide directory : {END}")
        try:
            all_info = get_df_by_dir(directory)
            get_results(all_info.get("file_data"), all_info.get("file_name"), all_info.get("sheet_name"))
        except (FileNotFoundError, Exception) as e:
            print(f"Get exception while extra data from {directory} with {e} {END}")
    elif choice == "99":
        print("Exiting...")
        exit()
    elif choice == "0":
        main()


if __name__ == "__main__":
    main()
