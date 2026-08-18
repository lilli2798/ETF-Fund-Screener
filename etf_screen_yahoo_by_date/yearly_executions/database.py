"""
SQLite Database Module for Yearly ETF Returns

This module manages the yearly returns data for ETF tickers in SQLite format.
It integrates with the main etf_screener database to enable cross-table queries
between yearly returns, fund scores, and other ETF data.

Database Schema:
    - yearly_returns: Normalized format (ticker, year, return_value)
    - analysis_results: Calculated metrics (better/worse counts, percentages)
    - yearly_ranks: Performance rankings per year (ticker, year, rank)
    - percentile_counts: Percentile bucket counts for each ticker

Integration:
    This module writes to the main etf_screener database (data/etf_screener.db)
    which also contains tables: runs, funds, fund_scores, concept_scores, 
    additional_metrics, morningstar.

Usage:
    from database import YearlyReturnsDatabase
    
    # Save yearly returns data
    with YearlyReturnsDatabase("path/to/database.db") as db:
        db.save_yearly_returns(df)  # df: ticker as index, years as columns
    
    # Save analysis results
    with YearlyReturnsDatabase("path/to/database.db") as db:
        db.save_analysis_results(result_df)
    
    # Retrieve data
    with YearlyReturnsDatabase("path/to/database.db") as db:
        returns_df = db.get_yearly_returns(tickers=['SPY', 'QQQ'], years=[2020, 2021])
        analysis_df = db.get_analysis_results(tickers=['SPY'])
"""

import sqlite3
import pandas as pd
from pathlib import Path
from typing import Optional


class YearlyReturnsDatabase:
    """
    Database manager for yearly ETF returns data.
    
    This class provides methods to save and retrieve yearly returns data,
    analysis results, rankings, and percentile counts in a normalized format
    that enables efficient SQL queries and joins with other ETF data.
    
    Attributes:
        db_path: Path to the SQLite database file
        conn: SQLite database connection
    """
    
    def __init__(self, db_path: str):
        """
        Initialize database connection.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.conn = None
        self._connect()
        self._create_tables()
    
    def _connect(self):
        """Establish database connection."""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
    
    def _create_tables(self):
        """Create database tables if they don't exist."""
        cursor = self.conn.cursor()
        
        # Yearly returns table (normalized format)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS yearly_returns (
                ticker TEXT NOT NULL,
                year INTEGER NOT NULL,
                return_value REAL,
                UNIQUE(ticker, year),
                PRIMARY KEY (ticker, year)
            )
        """)
        
        # Analysis results table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analysis_results (
                ticker TEXT PRIMARY KEY,
                total_columns INTEGER,
                no_null_columns INTEGER,
                better INTEGER,
                worst INTEGER,
                better_pct REAL,
                worst_pct REAL,
                better_worst_diff INTEGER
            )
        """)
        
        # Yearly ranks table (normalized format)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS yearly_ranks (
                ticker TEXT NOT NULL,
                year INTEGER NOT NULL,
                rank INTEGER,
                UNIQUE(ticker, year),
                PRIMARY KEY (ticker, year)
            )
        """)
        
        # Percentile counts table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS percentile_counts (
                ticker TEXT PRIMARY KEY,
                percentile_10 INTEGER DEFAULT 0,
                percentile_20 INTEGER DEFAULT 0,
                percentile_30 INTEGER DEFAULT 0,
                percentile_40 INTEGER DEFAULT 0,
                percentile_50 INTEGER DEFAULT 0,
                percentile_60 INTEGER DEFAULT 0,
                percentile_70 INTEGER DEFAULT 0,
                percentile_80 INTEGER DEFAULT 0,
                percentile_90 INTEGER DEFAULT 0,
                percentile_worse_10 INTEGER DEFAULT 0
            )
        """)
        
        # Create indexes for better query performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_yearly_returns_ticker ON yearly_returns(ticker)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_yearly_returns_year ON yearly_returns(year)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_yearly_ranks_ticker ON yearly_ranks(ticker)")
        
        self.conn.commit()
    
    def save_yearly_returns(self, df: pd.DataFrame):
        """
        Save yearly returns data to database (normalized format).
        
        Args:
            df: DataFrame with ticker as index and years as columns
        """
        cursor = self.conn.cursor()
        
        # Clear existing data (we'll replace with fresh data)
        cursor.execute("DELETE FROM yearly_returns")
        
        # Convert wide format to normalized format
        for ticker in df.index:
            for year_col in df.columns:
                if year_col.isdigit():
                    year = int(year_col)
                    return_value = df.loc[ticker, year_col]
                    if pd.notna(return_value):
                        cursor.execute(
                            "INSERT OR REPLACE INTO yearly_returns (ticker, year, return_value) VALUES (?, ?, ?)",
                            (ticker, year, return_value)
                        )
        
        self.conn.commit()
        print(f"Saved {len(df)} tickers to yearly_returns table")
    
    def save_analysis_results(self, result_df: pd.DataFrame):
        """
        Save analysis results to database.
        
        Args:
            result_df: DataFrame with analysis metrics
        """
        cursor = self.conn.cursor()
        
        # Clear existing analysis results
        cursor.execute("DELETE FROM analysis_results")
        cursor.execute("DELETE FROM yearly_ranks")
        cursor.execute("DELETE FROM percentile_counts")
        
        for ticker in result_df.index:
            # Save main analysis results
            cursor.execute("""
                INSERT OR REPLACE INTO analysis_results 
                (ticker, total_columns, no_null_columns, better, worst, better_pct, worst_pct, better_worst_diff)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ticker,
                int(result_df.loc[ticker, 'total_columns']),
                int(result_df.loc[ticker, 'no_null_columns']),
                int(result_df.loc[ticker, 'better']),
                int(result_df.loc[ticker, 'worst']),
                float(result_df.loc[ticker, 'better_%']),
                float(result_df.loc[ticker, 'worst_%']),
                int(result_df.loc[ticker, 'better_worst_diff'])
            ))
            
            # Save yearly ranks
            for col in result_df.columns:
                if col.startswith('Yearly_') and col.endswith('_rank'):
                    year = int(col.replace('Yearly_', '').replace('_rank', ''))
                    rank = result_df.loc[ticker, col]
                    if pd.notna(rank):
                        cursor.execute(
                            "INSERT OR REPLACE INTO yearly_ranks (ticker, year, rank) VALUES (?, ?, ?)",
                            (ticker, year, int(rank))
                        )
            
            # Save percentile counts
            percentile_cols = ['10%', '20%', '30%', '40%', '50%', '60%', '70%', '80%', '90%', 'worse_10%']
            percentile_values = [int(result_df.loc[ticker, col]) for col in percentile_cols]
            cursor.execute("""
                INSERT OR REPLACE INTO percentile_counts 
                (ticker, percentile_10, percentile_20, percentile_30, percentile_40, percentile_50,
                 percentile_60, percentile_70, percentile_80, percentile_90, percentile_worse_10)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [ticker] + percentile_values)
        
        self.conn.commit()
        print(f"Saved analysis results for {len(result_df)} tickers")
    
    def get_yearly_returns(self, tickers: Optional[list] = None, years: Optional[list] = None) -> pd.DataFrame:
        """
        Retrieve yearly returns data from database.
        
        Args:
            tickers: List of tickers to filter (optional)
            years: List of years to filter (optional)
        
        Returns:
            DataFrame in wide format (ticker as index, years as columns)
        """
        query = "SELECT ticker, year, return_value FROM yearly_returns"
        conditions = []
        params = []
        
        if tickers:
            placeholders = ','.join(['?' for _ in tickers])
            conditions.append(f"ticker IN ({placeholders})")
            params.extend(tickers)
        
        if years:
            placeholders = ','.join(['?' for _ in years])
            conditions.append(f"year IN ({placeholders})")
            params.extend(years)
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        df = pd.read_sql_query(query, self.conn, params=params)
        
        if df.empty:
            return df
        
        # Convert to wide format
        return df.pivot(index='ticker', columns='year', values='return_value')
    
    def get_analysis_results(self, tickers: Optional[list] = None) -> pd.DataFrame:
        """
        Retrieve analysis results from database.
        
        Args:
            tickers: List of tickers to filter (optional)
        
        Returns:
            DataFrame with analysis results
        """
        query = "SELECT * FROM analysis_results"
        params = []
        
        if tickers:
            placeholders = ','.join(['?' for _ in tickers])
            query += f" WHERE ticker IN ({placeholders})"
            params.extend(tickers)
        
        df = pd.read_sql_query(query, self.conn, params=params, index_col='ticker')
        return df
    
    def get_yearly_ranks(self, tickers: Optional[list] = None, years: Optional[list] = None) -> pd.DataFrame:
        """
        Retrieve yearly ranks from database.
        
        Args:
            tickers: List of tickers to filter (optional)
            years: List of years to filter (optional)
        
        Returns:
            DataFrame in wide format (ticker as index, years as columns)
        """
        query = "SELECT ticker, year, rank FROM yearly_ranks"
        conditions = []
        params = []
        
        if tickers:
            placeholders = ','.join(['?' for _ in tickers])
            conditions.append(f"ticker IN ({placeholders})")
            params.extend(tickers)
        
        if years:
            placeholders = ','.join(['?' for _ in years])
            conditions.append(f"year IN ({placeholders})")
            params.extend(years)
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        df = pd.read_sql_query(query, self.conn, params=params)
        
        if df.empty:
            return df
        
        # Convert to wide format
        return df.pivot(index='ticker', columns='year', values='rank')
    
    def get_percentile_counts(self, tickers: Optional[list] = None) -> pd.DataFrame:
        """
        Retrieve percentile counts from database.
        
        Args:
            tickers: List of tickers to filter (optional)
        
        Returns:
            DataFrame with percentile counts
        """
        query = "SELECT * FROM percentile_counts"
        params = []
        
        if tickers:
            placeholders = ','.join(['?' for _ in tickers])
            query += f" WHERE ticker IN ({placeholders})"
            params.extend(tickers)
        
        df = pd.read_sql_query(query, self.conn, params=params, index_col='ticker')
        return df
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


def get_database(db_path: str) -> YearlyReturnsDatabase:
    """
    Get a database instance.
    
    Args:
        db_path: Path to SQLite database file
    
    Returns:
        YearlyReturnsDatabase instance
    """
    return YearlyReturnsDatabase(db_path)
