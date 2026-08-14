"""
SQLite Database Module for ETF Screener Results

Stores historical screener results in a SQLite database for easy querying and filtering.
"""

import sqlite3
from datetime import datetime
from pathlib import Path
import pandas as pd
from typing import Optional, List, Dict, Any


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

        # Funds table - static fund information
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

        self.conn.commit()

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
            run_timestamp,
            profile_name,
            json.dumps(weights_dict),
            json.dumps(concept_weights_dict),
            len(df),
            len(df[df.get("Profile A Selected Flag", pd.Series([False] * len(df))) == True])
        ))

        # Save/update funds table (static fund information)
        fund_info_columns = {
            'ticker': 'Ticker',
            'name': 'Name',
            'morningstar_category': 'Morningstar Category',
            'asset_class': 'Asset Class',
            'inception_date': 'Inception Date',
            'primary_benchmark': 'Primary Benchmark',
            'equity_style_box': 'Equity Style Box (Funds)'
        }

        for _, row in df.iterrows():
            ticker = row.get('Ticker')
            if pd.notna(ticker):
                fund_data = {}
                for db_col, df_col in fund_info_columns.items():
                    if df_col in df.columns:
                        fund_data[db_col] = row[df_col]
                
                fund_data['last_updated'] = run_timestamp
                
                # Use INSERT OR REPLACE to update if ticker exists
                cursor.execute("""
                    INSERT OR REPLACE INTO funds 
                    (ticker, name, morningstar_category, asset_class, inception_date, primary_benchmark, equity_style_box, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    fund_data.get('ticker'),
                    fund_data.get('name'),
                    fund_data.get('morningstar_category'),
                    fund_data.get('asset_class'),
                    fund_data.get('inception_date'),
                    fund_data.get('primary_benchmark'),
                    fund_data.get('equity_style_box'),
                    fund_data.get('last_updated')
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
