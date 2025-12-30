"""
Load SEC Filing data into PostgreSQL database
Processes output from SECFilingCollector.py

Input files per ticker:
  - {ticker}_filings.csv: Individual filings with metadata
  - {ticker}_submissions_raw.json: Raw SEC API responses (optional)
"""
import json
import os
from dotenv import load_dotenv
import pandas as pd
from pathlib import Path
from datetime import datetime
import psycopg2
import psycopg2.errors
from psycopg2.extras import execute_batch
import logging
from typing import Dict, Optional

load_dotenv()


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SECFilingsLoader:
    """Load SEC Filings data from CSV files into PostgreSQL"""
    
    def __init__(self, db_params: Dict):
        """
        Args:
            db_params: Dict with database connection parameters
                      {'dbname': 'stock_events', 'user': 'postgres', 
                       'password': 'xxx', 'host': 'localhost', 'port': '5432'}
        """
        self.db_params = db_params
        self.conn = None
        self.cursor = None
        
        # Cache ticker IDs to avoid repeated lookups
        self.ticker_cache = {}
        
        # Statistics
        self.stats = {
            'filings_inserted': 0,
            'filings_skipped': 0,
            'tickers_created': 0,
            'tickers_fetched': 0,
            'by_form_type': {}
        }
    
    def connect(self):
        """Establish database connection"""
        try:
            self.conn = psycopg2.connect(**self.db_params)
            self.cursor = self.conn.cursor()
            logger.info("✓ Connected to database")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise
    
    def close(self):
        """Close database connection"""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        logger.info("✓ Database connection closed")
    
    def get_or_create_ticker(self, symbol: str) -> int:
        """
        Get ticker_id for a symbol, create if doesn't exist
        Uses cache to minimize database queries
        
        Args:
            symbol: Stock ticker symbol
        
        Returns:
            ticker_id (int)
        """
        symbol = symbol.upper()
        
        # Check cache first
        if symbol in self.ticker_cache:
            return self.ticker_cache[symbol]
        
        # Check database
        self.cursor.execute(
            "SELECT ticker_id FROM tickers WHERE symbol = %s",
            (symbol,)
        )
        result = self.cursor.fetchone()
        
        if result:
            ticker_id = result[0]
            self.ticker_cache[symbol] = ticker_id
            self.stats['tickers_fetched'] += 1
            return ticker_id
        
        # Create new ticker
        self.cursor.execute(
            """
            INSERT INTO tickers (symbol, created_at, updated_at)
            VALUES (%s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING ticker_id
            """,
            (symbol,)
        )
        ticker_id = self.cursor.fetchone()[0]
        self.ticker_cache[symbol] = ticker_id
        self.stats['tickers_created'] += 1
        self.conn.commit()
        
        return ticker_id
    
    def load_filings_from_csv(self, csv_path: str, ticker: str) -> pd.DataFrame:
        """
        Load filings from CSV file
        
        Args:
            csv_path: Path to CSV file
            ticker: Stock ticker symbol
        
        Returns:
            DataFrame with filings
        """
        if not Path(csv_path).exists():
            logger.warning(f"File not found: {csv_path}")
            return pd.DataFrame()
        
        df = pd.read_csv(csv_path)
        logger.info(f"Loaded {len(df)} filings from {csv_path}")
        
        # Validate required columns
        required_cols = ['ticker', 'accessionNumber', 'form', 'filingDate']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            logger.warning(f"Missing columns in CSV: {missing_cols}")
        
        return df
    
    def insert_filing(self,
                     ticker_id: int,
                     accession_number: str,
                     form_type: str,
                     filing_date: datetime,
                     filing_url: str,
                     period_end_date: Optional[datetime] = None,
                     acceptance_datetime: Optional[datetime] = None,
                     primary_document: Optional[str] = None,
                     primary_doc_description: Optional[str] = None,
                     form_category: Optional[str] = None,
                     items_parsed: Optional[str] = None,
                     document_text: Optional[str] = None) -> Optional[int]:
        """
        Insert a single SEC filing into the database
        
        Args:
            ticker_id: Ticker ID
            accession_number: SEC accession number
            form_type: Form type (10-K, 10-Q, 8-K, etc.)
            filing_date: Filing date
            filing_url: URL to filing document
            period_end_date: Report/period end date
            acceptance_datetime: SEC acceptance datetime
            primary_document: Primary document filename
            primary_doc_description: Description of primary document
            form_category: Categorization (for 8-K: Earnings, Management Change, etc.)
            items_parsed: Comma-separated parsed items (for 8-K)
            document_text: Full document text (optional, for full-text search)
        
        Returns:
            sec_filing_id if successful, None if duplicate
        """
        try:
            # Check if accession number already exists (avoid duplicates)
            self.cursor.execute(
                "SELECT filing_id FROM sec_filings WHERE accession_number = %s",
                (accession_number,)
            )
            
            if self.cursor.fetchone():
                self.stats['filings_skipped'] += 1
                return None
            
            # Insert filing
            self.cursor.execute(
                """
                INSERT INTO sec_filings 
                (ticker_id, accession_number, form_type, filing_date, period_end_date,
                 acceptance_datetime, primary_document, primary_doc_description,
                 filing_url, form_category, items_parsed, document_text, retrieved_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                RETURNING filing_id
                """,
                (ticker_id, accession_number, form_type, filing_date, period_end_date,
                 acceptance_datetime, primary_document, primary_doc_description,
                 filing_url, form_category, items_parsed, document_text)
            )
            
            filing_id = self.cursor.fetchone()[0]
            self.stats['filings_inserted'] += 1
            
            # Track by form type
            if form_type not in self.stats['by_form_type']:
                self.stats['by_form_type'][form_type] = 0
            self.stats['by_form_type'][form_type] += 1
            
            return filing_id
        
        except psycopg2.errors.UniqueViolation:
            # Handle unique constraint violations (duplicate accession number)
            self.conn.rollback()
            self.stats['filings_skipped'] += 1
            logger.debug(f"Filing {accession_number} already exists (skipped)")
            return None
        except Exception as e:
            # Rollback transaction on any other error to prevent "transaction aborted" errors
            self.conn.rollback()
            logger.warning(f"Error inserting filing {accession_number}: {e}")
            return None
    
    def load_ticker_filings(self, filings_csv: str, ticker: str, auto_commit: bool = True) -> int:
        """
        Load all filings for a ticker from CSV
        
        Args:
            filings_csv: Path to {ticker}_filings.csv
            ticker: Stock ticker symbol
            auto_commit: Whether to auto-commit changes
        
        Returns:
            Number of filings inserted
        """
        df = self.load_filings_from_csv(filings_csv, ticker)
        
        if df.empty:
            return 0
        
        # Get ticker ID
        ticker_id = self.get_or_create_ticker(ticker)
        
        initial_count = self.stats['filings_inserted']
        
        # Process each filing
        for idx, row in df.iterrows():
            try:
                # Parse dates
                filing_date = pd.to_datetime(row.get('filingDate'))
                period_end_date = None
                if pd.notna(row.get('reportDate')):
                    period_end_date = pd.to_datetime(row.get('reportDate'))
                
                acceptance_datetime = None
                if pd.notna(row.get('acceptanceDateTime')):
                    acceptance_datetime = pd.to_datetime(row.get('acceptanceDateTime'))
                
                # Extract form category and items (for 8-Ks)
                form_category = str(row.get('category', '')) if pd.notna(row.get('category')) else None
                items_parsed = str(row.get('items_str', '')) if pd.notna(row.get('items_str')) else None
                
                # Insert filing
                filing_id = self.insert_filing(
                    ticker_id=ticker_id,
                    accession_number=str(row.get('accessionNumber', '')),
                    form_type=str(row.get('form', '')),
                    filing_date=filing_date,
                    filing_url=str(row.get('filing_url', '')),
                    period_end_date=period_end_date,
                    acceptance_datetime=acceptance_datetime,
                    primary_document=str(row.get('primaryDocument', '')) if pd.notna(row.get('primaryDocument')) else None,
                    primary_doc_description=str(row.get('primaryDocDescription', '')) if pd.notna(row.get('primaryDocDescription')) else None,
                    form_category=form_category if form_category and form_category != 'Other' else None,
                    items_parsed=items_parsed if items_parsed else None
                )
                
                # Batch commit every 50 filings
                if (idx + 1) % 50 == 0:
                    if auto_commit:
                        self.conn.commit()
                        logger.info(f"Committed batch of 50 filings ({idx + 1}/{len(df)})")
            
            except Exception as e:
                logger.error(f"Error processing filing at row {idx}: {e}")
                continue
        
        # Final commit
        if auto_commit:
            self.conn.commit()
        
        inserted = self.stats['filings_inserted'] - initial_count
        logger.info(f"✓ Loaded {inserted} new filings for {ticker}")
        
        return inserted
    
    def load_all_tickers(self, data_dir: str = 'data/raw/sec_filings', auto_commit: bool = True) -> Dict:
        """
        Load filings for all tickers in the data directory
        
        Args:
            data_dir: Directory containing {ticker}_filings.csv files
            auto_commit: Whether to auto-commit changes
        
        Returns:
            Dictionary with load statistics
        """
        data_path = Path(data_dir)
        
        if not data_path.exists():
            logger.error(f"Data directory not found: {data_dir}")
            return self.stats
        
        # Find all filings CSV files
        filings_files = sorted(data_path.glob('*_filings.csv'))
        
        if not filings_files:
            logger.warning(f"No filings files found in {data_dir}")
            return self.stats
        
        logger.info(f"Found {len(filings_files)} filings files")
        
        # Load each ticker
        for csv_file in filings_files:
            try:
                # Extract ticker from filename
                ticker = csv_file.stem.replace('_filings', '')
                logger.info(f"\nLoading filings for {ticker}...")
                
                self.load_ticker_filings(str(csv_file), ticker, auto_commit=auto_commit)
            
            except Exception as e:
                logger.error(f"Failed to load {csv_file}: {e}")
                continue
        
        return self.stats
    
    def print_statistics(self):
        """Print loading statistics"""
        print("\n" + "="*60)
        print("SEC FILINGS LOADER STATISTICS")
        print("="*60)
        print(f"Filings inserted:   {self.stats['filings_inserted']:>10}")
        print(f"Filings skipped:    {self.stats['filings_skipped']:>10}")
        print(f"Tickers created:    {self.stats['tickers_created']:>10}")
        print(f"Tickers fetched:    {self.stats['tickers_fetched']:>10}")
        print("\nFitngs by form type:")
        for form_type, count in sorted(self.stats['by_form_type'].items()):
            print(f"  {form_type:8s}: {count:>6}")
        print("="*60 + "\n")


def main():
    """Example usage"""
    # Database configuration from environment variables
    DB_CONFIG = {
        'dbname': os.getenv('DB_NAME', 'stock_events'),
        'user': os.getenv('DB_USER', 'postgres'),
        'password': os.getenv('DB_PASSWORD', 'postgres'),
        'host': os.getenv('DB_HOST', 'localhost'),
        'port': os.getenv('DB_PORT', '5432')
    }
    
    # Initialize loader
    loader = SECFilingsLoader(DB_CONFIG)
    
    try:
        loader.connect()
        
        # Load all SEC filings from CSV files
        # Maps CSV columns to database fields:
        #   ticker → tickers.symbol (gets/creates ticker)
        #   accessionNumber → sec_filings.accession_number
        #   form → sec_filings.form_type
        #   filingDate → sec_filings.filing_date
        #   reportDate → sec_filings.period_end_date
        #   acceptanceDateTime → sec_filings.acceptance_datetime
        #   primaryDocument → sec_filings.primary_document
        #   primaryDocDescription → sec_filings.primary_doc_description
        #   filing_url → sec_filings.filing_url
        #   category → sec_filings.form_category (8-K categorization)
        #   items_str → sec_filings.items_parsed (8-K parsed items)
        
        print("Loading SEC filings from data/raw/sec_filings/")
        print("CSV columns being loaded:")
        print("  - accessionNumber, form, filingDate, reportDate, acceptanceDateTime")
        print("  - primaryDocument, primaryDocDescription, filing_url")
        print("  - category (8-K), items_str (8-K parsed items)")
        print()
        
        loader.load_all_tickers('data/raw/sec_filings')
        
        # Print statistics
        loader.print_statistics()
    
    except Exception as e:
        logger.error(f"Failed to load SEC filings data: {e}")
    
    finally:
        loader.close()


if __name__ == '__main__':
    main()
