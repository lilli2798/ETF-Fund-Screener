"""
SQLite Database Module for ETF Screener Results

Stores historical screener results in a SQLite database for easy querying and filtering.
"""

import sqlite3
from datetime import datetime
from pathlib import Path
import pandas as pd
from typing import Optional, List, Dict, Any
try:
    from config import NEEDED_COLS
except ImportError:
    from etf_screener.config import NEEDED_COLS


class ETFScreenerDatabase:
    """Manages SQLite database for ETF screener results."""

    def __init__(self, db_path: str = None):
        """
        Initialize database connection.

        Args:
            db_path: Path to SQLite database file. Defaults to data/etf_screener.db
        """
        if db_path is None:
            # Default to data directory in project root
            project_root = Path(__file__).parent.parent
            db_path = project_root / "data" / "etf_screener.db"

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(self.db_path)
        self._create_tables()

    def _create_tables(self):
        """Create database tables if they don't exist."""
        cursor = self.conn.cursor()

        # Runs table - metadata for each screener run
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                run_timestamp DATETIME,
                profile_name TEXT,
                weights_used TEXT,
                concept_weights TEXT,
                total_funds_count INTEGER,
                selected_funds_count INTEGER
            )
        """)

        # Funds table - static fund information with ratings
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS funds (
                ticker TEXT PRIMARY KEY,
                name TEXT,
                morningstar_category TEXT,
                asset_class TEXT,
                inception_date TEXT,
                primary_benchmark TEXT,
                equity_style_box TEXT,
                last_updated TIMESTAMP
            )
        """)

        # Add columns to funds table if they don't exist (for existing databases)
        columns_to_add = [
            'medalist_rating TEXT',
            'star_rating TEXT',
            'growth_grade TEXT',
            'financial_health_grade TEXT',
            'profitability_grade TEXT',
            'price_fair_value TEXT',
            'economic_moat_wide TEXT'
        ]

        for col_def in columns_to_add:
            col_name = col_def.split()[0]
            try:
                cursor.execute(f"ALTER TABLE funds ADD COLUMN {col_def}")
            except sqlite3.OperationalError:
                # Column already exists, ignore error
                pass

        # Morningstar raw data table - stores all source data (recreated each run)
        # This table does NOT keep history - it's dropped and recreated on each run
        self._create_morningstar_table(cursor)

        # Fund scores table - composite scores per fund per run
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fund_scores (
                run_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                profile_score REAL,
                rank_in_category INTEGER,
                rank_overall INTEGER,
                selected_flag_category BOOLEAN,
                selected_flag_overall BOOLEAN,
                PRIMARY KEY(run_id, ticker),
                FOREIGN KEY (run_id) REFERENCES runs(run_id),
                FOREIGN KEY (ticker) REFERENCES funds(ticker)
            )
        """)

        # Concept scores table - concept scores per fund per run
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS concept_scores (
                run_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                long_term_return_performance_score REAL,
                short_term_return_performance_score REAL,
                risk_adjusted_score REAL,
                volatility_score REAL,
                tracking_score REAL,
                liquidity_size_score REAL,
                quality_valuation_score REAL,
                costs_score REAL,
                tax_income_score REAL,
                PRIMARY KEY(run_id, ticker),
                FOREIGN KEY (run_id) REFERENCES runs(run_id),
                FOREIGN KEY (ticker) REFERENCES funds(ticker)
            )
        """)

        # Additional metrics table - additional metrics per fund per run
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS additional_metrics (
                run_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                better_worst_diff REAL,
                better_pct REAL,
                worst_pct REAL,
                worst_three_month_return REAL,
                PRIMARY KEY(run_id, ticker),
                FOREIGN KEY (run_id) REFERENCES runs(run_id),
                FOREIGN KEY (ticker) REFERENCES funds(ticker)
            )
        """)

        # Create indexes for common queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_runs_timestamp ON runs(run_timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_runs_profile ON runs(profile_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fund_scores_ticker ON fund_scores(ticker)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_concept_scores_ticker ON concept_scores(ticker)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_additional_metrics_ticker ON additional_metrics(ticker)")

    def _create_morningstar_table(self, cursor, df: pd.DataFrame = None):
        """Create or recreate the morningstar table with all columns from DataFrame.

        This table is dropped and recreated on each run to store the latest
        complete dataset (raw data + all computed results) without keeping history.

        Args:
            cursor: SQLite cursor
            df: DataFrame to use for column definitions. If None, uses NEEDED_COLS.
        """
        # Drop existing table if it exists
        cursor.execute("DROP TABLE IF EXISTS morningstar")

        # Determine columns to create
        if df is not None:
            columns = df.columns.tolist()
        else:
            columns = NEEDED_COLS

        # Create table with all columns
        # Convert column names to SQL-safe identifiers (replace spaces with underscores)
        columns_sql = []
        for col in columns:
            # Replace spaces and special characters with underscores for SQL column names
            sql_col = col.replace(" ", "_").replace("(", "").replace(")", "").replace("/", "_").replace("-", "_").replace("%", "_")
            # Add prefix if column name starts with a number (SQL identifiers can't start with numbers)
            if sql_col and sql_col[0].isdigit():
                sql_col = f"col_{sql_col}"
            # Use TEXT for all columns for simplicity - SQLite handles type conversion
            columns_sql.append(f'"{sql_col}" TEXT')

        columns_def = ",\n            ".join(columns_sql)

        cursor.execute(f"""
            CREATE TABLE morningstar (
                {columns_def}
            )
        """)

    def save_morningstar_data(self, df: pd.DataFrame) -> None:
        """Save complete dataset (raw data + all computed results) to the morningstar table.

        This replaces all existing data in the morningstar table with the
        provided DataFrame. The table is designed to hold the latest
        complete dataset without history.

        Args:
            df: DataFrame containing the complete dataset with all columns
        """
        cursor = self.conn.cursor()

        # Recreate table with current DataFrame columns
        self._create_morningstar_table(cursor, df)

        # Prepare column mapping from DataFrame to SQL column names
        column_mapping = {}
        for col in df.columns:
            # Convert column name to SQL-safe identifier
            sql_col = col.replace(" ", "_").replace("(", "").replace(")", "").replace("/", "_").replace("-", "_").replace("%", "_")
            # Add prefix if column name starts with a number (SQL identifiers can't start with numbers)
            if sql_col and sql_col[0].isdigit():
                sql_col = f"col_{sql_col}"
            column_mapping[col] = sql_col

        if not column_mapping:
            print("Warning: No columns found in DataFrame for morningstar table")
            return

        # Build INSERT statement
        sql_cols = list(column_mapping.values())
        placeholders = ", ".join(["?"] * len(sql_cols))
        insert_sql = f"""
            INSERT INTO morningstar ({", ".join(sql_cols)})
            VALUES ({placeholders})
        """

        # Insert data
        inserted_count = 0
        for _, row in df.iterrows():
            values = []
            for df_col in column_mapping.keys():
                value = row.get(df_col)
                # Convert NaN to None for SQL NULL
                if pd.isna(value):
                    values.append(None)
                # Convert datetime/timestamp to string
                elif hasattr(value, 'strftime'):
                    values.append(str(value))
                else:
                    values.append(value)

            try:
                cursor.execute(insert_sql, values)
                inserted_count += 1
            except Exception as e:
                print(f"Warning: Failed to insert row for ticker {row.get('Ticker', 'unknown')}: {e}")

        self.conn.commit()
        print(f"Saved {inserted_count} rows to morningstar table")

    def list_tables(self) -> List[str]:
        """
        List all tables in the database.

        Returns:
            List of table names
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
        return tables

    def save_results(
        self,
        df: pd.DataFrame,
        profile_name: str,
        weights: Dict[str, Any],
        run_id: str = None
    ) -> str:
        """
        Save screener results to database.

        Args:
            df: DataFrame with screener results
            profile_name: Name of the profile used
            weights: Thresholds dictionary (contains weights, concept_weights, etc.)
            run_id: Optional custom run ID (auto-generated if not provided)

        Returns:
            run_id: The ID of this run
        """
        import json
        
        if run_id is None:
            run_id = f"{profile_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        run_timestamp = datetime.now()

        # Extract weights and concept_weights
        weights_dict = weights.get("weights", {})
        concept_weights_dict = weights.get("concept_weights", {})

        cursor = self.conn.cursor()

        # Save to runs table
        cursor.execute("""
            INSERT OR REPLACE INTO runs 
            (run_id, run_timestamp, profile_name, weights_used, concept_weights, total_funds_count, selected_funds_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id,
            str(run_timestamp),
            profile_name,
            json.dumps(weights_dict),
            json.dumps(concept_weights_dict),
            len(df),
            len(df[df.get("Profile A Selected Flag", pd.Series([False] * len(df))) == True])
        ))

        # Save/update funds table (static fund information with ratings)
        fund_info_columns = {
            'ticker': 'Ticker',
            'name': 'Name',
            'morningstar_category': 'Morningstar Category',
            'asset_class': 'Asset Class',
            'inception_date': 'Inception Date',
            'primary_benchmark': 'Primary Benchmark',
            'equity_style_box': 'Equity Style Box (Funds)',
            'medalist_rating': 'Medalist Rating (Overall)',
            'star_rating': 'Morningstar Rating for Funds (Overall)',
            'growth_grade': 'Portfolio Growth Grade',
            'financial_health_grade': 'Portfolio Financial Health Grade',
            'profitability_grade': 'Portfolio Profitability Grade',
            'price_fair_value': 'Price/Fair Value',
            'economic_moat_wide': 'Portfolio Economic Moat Coverage (Wide)'
        }

        for _, row in df.iterrows():
            ticker = row.get('Ticker')
            if pd.notna(ticker):
                fund_data = {}
                for db_col, df_col in fund_info_columns.items():
                    if df_col in df.columns:
                        fund_data[db_col] = row[df_col]
                
                fund_data['last_updated'] = str(run_timestamp)
                
                # Convert any Timestamp or datetime objects to strings
                for key, value in fund_data.items():
                    if pd.notna(value) and hasattr(value, 'strftime'):
                        fund_data[key] = str(value)
                
                # Use INSERT OR REPLACE to update if ticker exists
                cursor.execute("""
                    INSERT OR REPLACE INTO funds 
                    (ticker, name, morningstar_category, asset_class, inception_date, primary_benchmark, equity_style_box, last_updated, medalist_rating, star_rating, growth_grade, financial_health_grade, price_fair_value, economic_moat_wide)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    fund_data.get('ticker'),
                    fund_data.get('name'),
                    fund_data.get('morningstar_category'),
                    fund_data.get('asset_class'),
                    fund_data.get('inception_date'),
                    fund_data.get('primary_benchmark'),
                    fund_data.get('equity_style_box'),
                    fund_data.get('last_updated'),
                    fund_data.get('medalist_rating'),
                    fund_data.get('star_rating'),
                    fund_data.get('growth_grade'),
                    fund_data.get('financial_health_grade'),
                    fund_data.get('price_fair_value'),
                    fund_data.get('economic_moat_wide')
                ))

        # Save to fund_scores table
        fund_score_columns = {
            'profile_score': 'Profile A Score',
            'rank_in_category': 'Profile A Rank In Category',
            'rank_overall': 'Profile A Rank Overall',
            'selected_flag_category': 'Profile A Selected Flag',
            'selected_flag_overall': 'Profile A Selected Overall Flag'
        }

        for _, row in df.iterrows():
            ticker = row.get('Ticker')
            if pd.notna(ticker):
                score_data = {}
                for db_col, df_col in fund_score_columns.items():
                    if df_col in df.columns:
                        score_data[db_col] = row[df_col]
                
                cursor.execute("""
                    INSERT OR REPLACE INTO fund_scores 
                    (run_id, ticker, profile_score, rank_in_category, rank_overall, selected_flag_category, selected_flag_overall)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    run_id,
                    ticker,
                    score_data.get('profile_score'),
                    score_data.get('rank_in_category'),
                    score_data.get('rank_overall'),
                    score_data.get('selected_flag_category'),
                    score_data.get('selected_flag_overall')
                ))

        # Save to concept_scores table
        concept_score_columns = {
            'long_term_return_performance_score': 'Long Term Return Performance Score',
            'short_term_return_performance_score': 'Short Term Return Performance Score',
            'risk_adjusted_score': 'Risk Adjusted Score',
            'volatility_score': 'Volatility Score',
            'tracking_score': 'Tracking Score',
            'liquidity_size_score': 'Liquidity Size Score',
            'quality_valuation_score': 'Quality Valuation Score',
            'costs_score': 'Costs Score',
            'tax_income_score': 'Tax Income Score'
        }

        for _, row in df.iterrows():
            ticker = row.get('Ticker')
            if pd.notna(ticker):
                concept_data = {}
                for db_col, df_col in concept_score_columns.items():
                    if df_col in df.columns:
                        concept_data[db_col] = row[df_col]
                
                cursor.execute("""
                    INSERT OR REPLACE INTO concept_scores 
                    (run_id, ticker, long_term_return_performance_score, short_term_return_performance_score,
                     risk_adjusted_score, volatility_score, tracking_score, liquidity_size_score,
                     quality_valuation_score, costs_score, tax_income_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    run_id,
                    ticker,
                    concept_data.get('long_term_return_performance_score'),
                    concept_data.get('short_term_return_performance_score'),
                    concept_data.get('risk_adjusted_score'),
                    concept_data.get('volatility_score'),
                    concept_data.get('tracking_score'),
                    concept_data.get('liquidity_size_score'),
                    concept_data.get('quality_valuation_score'),
                    concept_data.get('costs_score'),
                    concept_data.get('tax_income_score')
                ))

        # Save to additional_metrics table
        additional_metric_columns = {
            'better_worst_diff': 'Better Worst Diff',
            'better_pct': 'Better %',
            'worst_pct': 'Worst %',
            'worst_three_month_return': 'Worst Three Month Return'
        }

        for _, row in df.iterrows():
            ticker = row.get('Ticker')
            if pd.notna(ticker):
                metric_data = {}
                for db_col, df_col in additional_metric_columns.items():
                    if df_col in df.columns:
                        metric_data[db_col] = row[df_col]
                
                cursor.execute("""
                    INSERT OR REPLACE INTO additional_metrics 
                    (run_id, ticker, better_worst_diff, better_pct, worst_pct, worst_three_month_return)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    run_id,
                    ticker,
                    metric_data.get('better_worst_diff'),
                    metric_data.get('better_pct'),
                    metric_data.get('worst_pct'),
                    metric_data.get('worst_three_month_return')
                ))

        self.conn.commit()
        print(f"Results saved to database with run_id: {run_id}")
        return run_id

    def get_run_ids(self, profile_name: str = None, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Get list of run IDs with metadata.

        Args:
            profile_name: Filter by profile name (optional)
            limit: Maximum number of runs to return

        Returns:
            List of dictionaries with run metadata
        """
        cursor = self.conn.cursor()

        if profile_name:
            cursor.execute("""
                SELECT run_id, run_timestamp, profile_name, total_funds_count, selected_funds_count
                FROM runs
                WHERE profile_name = ?
                ORDER BY run_timestamp DESC
                LIMIT ?
            """, (profile_name, limit))
        else:
            cursor.execute("""
                SELECT run_id, run_timestamp, profile_name, total_funds_count, selected_funds_count
                FROM runs
                ORDER BY run_timestamp DESC
                LIMIT ?
            """, (limit,))

        columns = ['run_id', 'run_timestamp', 'profile_name', 'total_funds_count', 'selected_funds_count']
        results = []
        for row in cursor.fetchall():
            results.append(dict(zip(columns, row)))

        return results

    def get_results_by_run_id(self, run_id: str) -> Optional[pd.DataFrame]:
        """
        Retrieve full results for a specific run by joining all tables.

        Args:
            run_id: The run ID to retrieve

        Returns:
            DataFrame with results, or None if not found
        """
        cursor = self.conn.cursor()
        
        # Check if run exists
        cursor.execute("SELECT run_id FROM runs WHERE run_id = ?", (run_id,))
        if not cursor.fetchone():
            return None
        
        # Join all tables to get complete results
        query = """
            SELECT 
                f.ticker,
                f.name,
                f.morningstar_category,
                f.asset_class,
                f.inception_date,
                f.primary_benchmark,
                f.equity_style_box,
                fs.profile_score,
                fs.rank_in_category,
                fs.rank_overall,
                fs.selected_flag_category,
                fs.selected_flag_overall,
                cs.long_term_return_performance_score,
                cs.short_term_return_performance_score,
                cs.risk_adjusted_score,
                cs.volatility_score,
                cs.tracking_score,
                cs.liquidity_size_score,
                cs.quality_valuation_score,
                cs.costs_score,
                cs.tax_income_score,
                am.better_worst_diff,
                am.better_pct,
                am.worst_pct,
                am.worst_three_month_return
            FROM fund_scores fs
            JOIN funds f ON fs.ticker = f.ticker
            JOIN concept_scores cs ON fs.run_id = cs.run_id AND fs.ticker = cs.ticker
            LEFT JOIN additional_metrics am ON fs.run_id = am.run_id AND fs.ticker = am.ticker
            WHERE fs.run_id = ?
        """
        
        df = pd.read_sql_query(query, self.conn, params=(run_id,))
        return df

    def query_funds(
        self,
        profile_name: str = None,
        ticker: str = None,
        min_score: float = None,
        max_score: float = None,
        category: str = None,
        limit: int = 100
    ) -> pd.DataFrame:
        """
        Query fund results with filters.

        Args:
            profile_name: Filter by profile name
            ticker: Filter by ticker (partial match)
            min_score: Minimum profile score
            max_score: Maximum profile score
            category: Filter by Morningstar category (partial match)
            limit: Maximum number of results

        Returns:
            DataFrame with matching fund results
        """
        query = """
            SELECT 
                fs.run_id,
                r.run_timestamp,
                r.profile_name,
                f.ticker,
                f.name,
                f.morningstar_category,
                fs.profile_score,
                fs.rank_in_category,
                fs.rank_overall,
                fs.selected_flag_category,
                fs.selected_flag_overall
            FROM fund_scores fs
            JOIN funds f ON fs.ticker = f.ticker
            JOIN runs r ON fs.run_id = r.run_id
            WHERE 1=1
        """
        params = []

        if profile_name:
            query += " AND r.profile_name = ?"
            params.append(profile_name)

        if ticker:
            query += " AND f.ticker LIKE ?"
            params.append(f"%{ticker}%")

        if min_score is not None:
            query += " AND fs.profile_score >= ?"
            params.append(min_score)

        if max_score is not None:
            query += " AND fs.profile_score <= ?"
            params.append(max_score)

        if category:
            query += " AND f.morningstar_category LIKE ?"
            params.append(f"%{category}%")

        query += " ORDER BY fs.profile_score DESC LIMIT ?"
        params.append(limit)

        df = pd.read_sql_query(query, self.conn, params=params)
        return df

    def compare_metric_between_runs(
        self,
        metric: str,
        old_run_id: str = None,
        new_run_id: str = None,
        limit: int = 20
    ) -> pd.DataFrame:
        """
        Compare a specific metric between two runs to find funds with increasing values.

        Args:
            metric: Column name to compare (e.g., 'better_worst_diff', 'profile_score')
            old_run_id: Optional specific old run ID (if None, uses second most recent)
            new_run_id: Optional specific new run ID (if None, uses most recent)
            limit: Maximum number of results

        Returns:
            DataFrame with funds showing metric increase
        """
        # If run IDs not provided, get the two most recent runs
        if not old_run_id or not new_run_id:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT run_id FROM runs 
                ORDER BY run_timestamp DESC 
                LIMIT 2
            """)
            runs = cursor.fetchall()
            if len(runs) < 2:
                return pd.DataFrame()
            if not new_run_id:
                new_run_id = runs[0][0]
            if not old_run_id:
                old_run_id = runs[1][0]

        # Determine which table to query based on metric
        if metric in ['better_worst_diff', 'better_pct', 'worst_pct', 'worst_three_month_return']:
            table = 'additional_metrics'
        elif metric in ['long_term_return_performance_score', 'short_term_return_performance_score', 
                       'risk_adjusted_score', 'volatility_score', 'tracking_score', 
                       'liquidity_size_score', 'quality_valuation_score', 'costs_score', 'tax_income_score']:
            table = 'concept_scores'
        elif metric in ['profile_score', 'rank_in_category', 'rank_overall']:
            table = 'fund_scores'
        else:
            return pd.DataFrame()

        query = f"""
            SELECT 
                a.ticker,
                a.{metric} AS old_value,
                b.{metric} AS new_value,
                b.{metric} - a.{metric} AS increase,
                ra.run_timestamp AS old_run_date,
                rb.run_timestamp AS new_run_date
            FROM {table} a
            JOIN {table} b ON a.ticker = b.ticker
            JOIN runs ra ON a.run_id = ra.run_id
            JOIN runs rb ON b.run_id = rb.run_id
            WHERE a.run_id = ? AND b.run_id = ?
              AND b.{metric} > a.{metric}
            ORDER BY increase DESC
            LIMIT ?
        """

        df = pd.read_sql_query(query, self.conn, params=(old_run_id, new_run_id, limit))
        return df

    def query_funds_by_concept_scores(
        self,
        profile_name: str = None,
        ticker: str = None,
        category: str = None,
        min_long_term_score: float = None,
        min_short_term_score: float = None,
        min_risk_adjusted_score: float = None,
        min_volatility_score: float = None,
        min_tracking_score: float = None,
        min_liquidity_score: float = None,
        min_quality_score: float = None,
        min_costs_score: float = None,
        limit: int = 100
    ) -> pd.DataFrame:
        """
        Query funds with concept score filters.

        Args:
            profile_name: Filter by profile name
            ticker: Filter by ticker (partial match)
            category: Filter by Morningstar category (partial match)
            min_long_term_score: Minimum long term return performance score
            min_short_term_score: Minimum short term return performance score
            min_risk_adjusted_score: Minimum risk adjusted score
            min_volatility_score: Minimum volatility score
            min_tracking_score: Minimum tracking score
            min_liquidity_score: Minimum liquidity size score
            min_quality_score: Minimum quality valuation score
            min_costs_score: Minimum costs score
            limit: Maximum number of results

        Returns:
            DataFrame with matching fund results
        """
        query = """
            SELECT 
                fs.run_id,
                r.run_timestamp,
                r.profile_name,
                f.ticker,
                f.name,
                f.morningstar_category,
                fs.profile_score,
                fs.rank_in_category,
                cs.long_term_return_performance_score,
                cs.short_term_return_performance_score,
                cs.risk_adjusted_score,
                cs.volatility_score,
                cs.tracking_score,
                cs.liquidity_size_score,
                cs.quality_valuation_score,
                cs.costs_score
            FROM fund_scores fs
            JOIN funds f ON fs.ticker = f.ticker
            JOIN concept_scores cs ON fs.run_id = cs.run_id AND fs.ticker = cs.ticker
            JOIN runs r ON fs.run_id = r.run_id
            WHERE 1=1
        """
        params = []

        if profile_name:
            query += " AND r.profile_name = ?"
            params.append(profile_name)

        if ticker:
            query += " AND f.ticker LIKE ?"
            params.append(f"%{ticker}%")

        if category:
            query += " AND f.morningstar_category LIKE ?"
            params.append(f"%{category}%")

        if min_long_term_score is not None:
            query += " AND cs.long_term_return_performance_score >= ?"
            params.append(min_long_term_score)

        if min_short_term_score is not None:
            query += " AND cs.short_term_return_performance_score >= ?"
            params.append(min_short_term_score)

        if min_risk_adjusted_score is not None:
            query += " AND cs.risk_adjusted_score >= ?"
            params.append(min_risk_adjusted_score)

        if min_volatility_score is not None:
            query += " AND cs.volatility_score >= ?"
            params.append(min_volatility_score)

        if min_tracking_score is not None:
            query += " AND cs.tracking_score >= ?"
            params.append(min_tracking_score)

        if min_liquidity_score is not None:
            query += " AND cs.liquidity_size_score >= ?"
            params.append(min_liquidity_score)

        if min_quality_score is not None:
            query += " AND cs.quality_valuation_score >= ?"
            params.append(min_quality_score)

        if min_costs_score is not None:
            query += " AND cs.costs_score >= ?"
            params.append(min_costs_score)

        query += " ORDER BY fs.profile_score DESC LIMIT ?"
        params.append(limit)

        df = pd.read_sql_query(query, self.conn, params=params)
        return df

    def update_fund_ratings(self, df: pd.DataFrame):
        """
        Update fund ratings in the funds table from a DataFrame.
        Useful for monthly rating updates without running full screener.

        Args:
            df: DataFrame containing fund data with rating columns
        """
        import datetime
        
        cursor = self.conn.cursor()
        update_timestamp = datetime.datetime.now()
        
        # Map DataFrame columns to database columns
        rating_columns = {
            'medalist_rating': 'Medalist Rating (Overall)',
            'star_rating': 'Morningstar Rating for Funds (Overall)',
            'growth_grade': 'Portfolio Growth Grade',
            'financial_health_grade': 'Portfolio Financial Health Grade',
            'profitability_grade': 'Portfolio Profitability Grade',
            'price_fair_value': 'Price/Fair Value',
            'economic_moat_wide': 'Portfolio Economic Moat Coverage (Wide)'
        }
        
        updated_count = 0
        
        for _, row in df.iterrows():
            ticker = row.get('Ticker')
            if pd.notna(ticker):
                # Build update data
                update_data = {'last_updated': str(update_timestamp)}
                for db_col, df_col in rating_columns.items():
                    if df_col in df.columns:
                        update_data[db_col] = row[df_col]
                
                # Convert datetime objects to strings
                for key, value in update_data.items():
                    if pd.notna(value) and hasattr(value, 'strftime'):
                        update_data[key] = str(value)
                
                # Check if fund exists
                cursor.execute("SELECT ticker FROM funds WHERE ticker = ?", (ticker,))
                if cursor.fetchone():
                    # Update existing fund
                    set_clause = ", ".join([f"{col} = ?" for col in update_data.keys()])
                    query = f"UPDATE funds SET {set_clause} WHERE ticker = ?"
                    params = list(update_data.values()) + [ticker]
                    cursor.execute(query, params)
                    updated_count += 1
                else:
                    # Insert new fund
                    # Get basic info if available
                    basic_columns = {
                        'ticker': 'Ticker',
                        'name': 'Name',
                        'morningstar_category': 'Morningstar Category',
                        'asset_class': 'Asset Class',
                        'inception_date': 'Inception Date',
                        'primary_benchmark': 'Primary Benchmark',
                        'equity_style_box': 'Equity Style Box (Funds)'
                    }
                    for db_col, df_col in basic_columns.items():
                        if df_col in df.columns:
                            update_data[db_col] = row[df_col]
                    
                    # Convert datetime objects to strings
                    for key, value in update_data.items():
                        if pd.notna(value) and hasattr(value, 'strftime'):
                            update_data[key] = str(value)
                    
                    all_columns = list(update_data.keys())
                    placeholders = ", ".join(["?"] * len(all_columns))
                    columns_str = ", ".join(all_columns)
                    query = f"INSERT INTO funds ({columns_str}) VALUES ({placeholders})"
                    cursor.execute(query, list(update_data.values()))
                    updated_count += 1
        
        self.conn.commit()
        return updated_count

    def get_latest_run_for_profile(self, profile_name: str) -> Optional[str]:
        """
        Get the most recent run ID for a profile.

        Args:
            profile_name: Profile name

        Returns:
            run_id or None if no runs found
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT run_id FROM runs
            WHERE profile_name = ?
            ORDER BY run_timestamp DESC
            LIMIT 1
        """, (profile_name,))
        row = cursor.fetchone()
        return row[0] if row else None

    def close(self):
        """Close database connection."""
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Convenience function for quick access
def get_database(db_path: str = None) -> ETFScreenerDatabase:
    """Get a database instance."""
    return ETFScreenerDatabase(db_path)
