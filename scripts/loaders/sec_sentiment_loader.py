"""
Load SEC Filing Sentiment data into PostgreSQL database
Processes output from SECFilingsSentimentCollector.py

Input files per ticker:
  - {ticker}_filings_sentiment.json: Individual filings with sentiment scores
  - {ticker}_daily_sentiment.csv: Daily aggregated sentiment metrics
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


class SECSentimentLoader:
    """Load SEC Filing Sentiment data from JSON files into PostgreSQL"""
    
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
        
        # Cache ticker IDs and filing IDs to avoid repeated lookups
        self.ticker_cache = {}
        self.filing_cache = {}
        
        # Statistics
        self.stats = {
            'sentiments_inserted': 0,
            'sentiments_skipped': 0,
            'tickers_fetched': 0,
            'filings_not_found': 0
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
    
    def get_ticker_id(self, symbol: str) -> Optional[int]:
        """
        Get ticker_id for a symbol
        Uses cache to minimize database queries
        
        Args:
            symbol: Stock ticker symbol
        
        Returns:
            ticker_id (int) or None if not found
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
        
        return None
    
    def get_filing_id(self, accession_number: str) -> Optional[int]:
        """
        Get filing_id for an accession number
        Uses cache to minimize database queries
        
        Args:
            accession_number: SEC accession number
        
        Returns:
            filing_id (int) or None if not found
        """
        # Check cache first
        if accession_number in self.filing_cache:
            return self.filing_cache[accession_number]
        
        # Check database
        self.cursor.execute(
            "SELECT filing_id FROM sec_filings WHERE accession_number = %s",
            (accession_number,)
        )
        result = self.cursor.fetchone()
        
        if result:
            filing_id = result[0]
            self.filing_cache[accession_number] = filing_id
            return filing_id
        
        self.stats['filings_not_found'] += 1
        return None
    
    def load_filings_from_json(self, json_file: str, ticker: str) -> list:
        """
        Load filings with sentiment from JSON file
        
        Args:
            json_file: Path to {ticker}_filings_sentiment.json
            ticker: Stock ticker symbol
        
        Returns:
            List of filing dictionaries
        """
        if not Path(json_file).exists():
            logger.warning(f"File not found: {json_file}")
            return []
        
        try:
            with open(json_file, 'r') as f:
                filings = json.load(f)
            
            logger.info(f"Loaded {len(filings)} filings from {Path(json_file).name}")
            return filings
        
        except Exception as e:
            logger.error(f"Failed to load {json_file}: {e}")
            return []
    
    def classify_sentiment_label(self, sentiment_score: float) -> str:
        """
        Classify sentiment score into a label
        
        Args:
            sentiment_score: Sentiment score between -1 and 1
        
        Returns:
            Sentiment label: 'positive', 'negative', or 'neutral'
        """
        if sentiment_score > 0.1:
            return 'positive'
        elif sentiment_score < -0.1:
            return 'negative'
        else:
            return 'neutral'
    
    def insert_filing_sentiment(self,
                                filing_id: int,
                                ticker_id: int,
                                sentiment_score: float,
                                section: str = 'overall',
                                model_name: str = 'rule_based_v1') -> Optional[int]:
        """
        Insert sentiment for a filing into the database
        
        Args:
            filing_id: Filing ID from sec_filings table
            ticker_id: Ticker ID
            sentiment_score: Sentiment score between -1 and 1
            section: Section of filing analyzed (default: 'overall')
            model_name: Name of sentiment model used
        
        Returns:
            sentiment_id if successful, None if duplicate or error
        """
        try:
            # Check if sentiment already exists for this filing and section
            self.cursor.execute(
                "SELECT sentiment_id FROM sec_filing_sentiment WHERE filing_id = %s AND section = %s",
                (filing_id, section)
            )
            
            if self.cursor.fetchone():
                self.stats['sentiments_skipped'] += 1
                return None
            
            # Classify sentiment
            sentiment_label = self.classify_sentiment_label(sentiment_score)
            
            # For rule-based sentiment, we don't have positive/negative/neutral scores
            # Set them based on the label
            positive_score = 1.0 if sentiment_label == 'positive' else 0.0
            negative_score = 1.0 if sentiment_label == 'negative' else 0.0
            neutral_score = 1.0 if sentiment_label == 'neutral' else 0.0
            
            # Insert sentiment
            self.cursor.execute(
                """
                INSERT INTO sec_filing_sentiment 
                (filing_id, ticker_id, section, sentiment_label, sentiment_score,
                 positive_score, negative_score, neutral_score, model_name, model_version)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING sentiment_id
                """,
                (filing_id, ticker_id, section, sentiment_label, sentiment_score,
                 positive_score, negative_score, neutral_score, model_name, '1.0')
            )
            
            sentiment_id = self.cursor.fetchone()[0]
            self.stats['sentiments_inserted'] += 1
            
            return sentiment_id
        
        except psycopg2.errors.UniqueViolation:
            # Handle unique constraint violations
            self.conn.rollback()
            self.stats['sentiments_skipped'] += 1
            logger.debug(f"Sentiment for filing {filing_id}, section {section} already exists (skipped)")
            return None
        except Exception as e:
            # Rollback transaction on any error to prevent "transaction aborted" errors
            self.conn.rollback()
            logger.warning(f"Error inserting sentiment for filing {filing_id}: {e}")
            return None
    
    def load_ticker_sentiments(self, json_file: str, ticker: str, auto_commit: bool = True) -> int:
        """
        Load all filing sentiments for a ticker from JSON
        
        Args:
            json_file: Path to {ticker}_filings_sentiment.json
            ticker: Stock ticker symbol
            auto_commit: Whether to auto-commit changes
        
        Returns:
            Number of sentiments inserted
        """
        filings = self.load_filings_from_json(json_file, ticker)
        
        if not filings:
            return 0
        
        # Get ticker ID
        ticker_id = self.get_ticker_id(ticker)
        if not ticker_id:
            logger.error(f"Ticker {ticker} not found in database")
            return 0
        
        initial_count = self.stats['sentiments_inserted']
        
        # Process each filing
        for idx, filing in enumerate(filings):
            try:
                accession_number = filing.get('accession_number')
                sentiment_score = filing.get('sentiment')
                
                if not accession_number:
                    logger.warning(f"Missing accession_number in filing at index {idx}")
                    continue
                
                if sentiment_score is None:
                    logger.warning(f"Missing sentiment for filing {accession_number}")
                    continue
                
                # Get filing_id
                filing_id = self.get_filing_id(accession_number)
                if not filing_id:
                    logger.warning(f"Filing {accession_number} not found in database (may need to run sec_filings_loader first)")
                    continue
                
                # Insert sentiment
                self.insert_filing_sentiment(
                    filing_id=filing_id,
                    ticker_id=ticker_id,
                    sentiment_score=float(sentiment_score),
                    section='overall',
                    model_name='rule_based_form_type'
                )
                
                # Batch commit every 50 sentiments
                if (idx + 1) % 50 == 0:
                    if auto_commit:
                        self.conn.commit()
                        logger.info(f"Committed batch of 50 sentiments ({idx + 1}/{len(filings)})")
            
            except Exception as e:
                logger.error(f"Error processing filing at index {idx}: {e}")
                continue
        
        # Final commit
        if auto_commit:
            self.conn.commit()
        
        inserted = self.stats['sentiments_inserted'] - initial_count
        logger.info(f"✓ Loaded {inserted} new sentiments for {ticker}")
        
        return inserted
    
    def load_all_tickers(self, data_dir: str = 'data/processed/sec-sentiment', auto_commit: bool = True) -> Dict:
        """
        Load sentiments for all tickers in the data directory
        
        Args:
            data_dir: Directory containing {ticker}_filings_sentiment.json files
            auto_commit: Whether to auto-commit changes
        
        Returns:
            Dictionary with load statistics
        """
        data_path = Path(data_dir)
        
        if not data_path.exists():
            logger.error(f"Data directory not found: {data_dir}")
            return self.stats
        
        # Find all sentiment JSON files
        sentiment_files = sorted(data_path.glob('*_filings_sentiment.json'))
        
        if not sentiment_files:
            logger.warning(f"No sentiment files found in {data_dir}")
            return self.stats
        
        logger.info(f"Found {len(sentiment_files)} sentiment files")
        
        # Load each ticker
        for json_file in sentiment_files:
            try:
                # Extract ticker from filename
                ticker = json_file.stem.replace('_filings_sentiment', '')
                logger.info(f"\nLoading sentiments for {ticker}...")
                
                self.load_ticker_sentiments(str(json_file), ticker, auto_commit=auto_commit)
            
            except Exception as e:
                logger.error(f"Failed to load {json_file}: {e}")
                continue
        
        return self.stats
    
    def print_statistics(self):
        """Print loading statistics"""
        print("\n" + "="*60)
        print("SEC FILING SENTIMENT LOADER STATISTICS")
        print("="*60)
        print(f"Sentiments inserted:       {self.stats['sentiments_inserted']:5d}")
        print(f"Sentiments skipped:        {self.stats['sentiments_skipped']:5d}")
        print(f"Tickers fetched:           {self.stats['tickers_fetched']:5d}")
        print(f"Filings not found:         {self.stats['filings_not_found']:5d}")
        print("="*60)


def main():
    """Main execution"""
    # Database connection parameters
    db_params = {
        'dbname': os.getenv('DB_NAME', 'stock_events'),
        'user': os.getenv('DB_USER', 'postgres'),
        'password': os.getenv('DB_PASSWORD'),
        'host': os.getenv('DB_HOST', 'localhost'),
        'port': os.getenv('DB_PORT', '5432')
    }
    
    loader = SECSentimentLoader(db_params)
    
    try:
        # Connect to database
        loader.connect()
        
        # Load all ticker sentiments
        print("\nLoading SEC filing sentiments from data/processed/sec-sentiment/")
        print("Sentiment model: rule-based (form type classification)")
        print()
        
        loader.load_all_tickers(
            data_dir='data/processed/sec-sentiment',
            auto_commit=True
        )
        
        # Print statistics
        loader.print_statistics()
        
    except Exception as e:
        logger.error(f"Loader failed: {e}")
        raise
    
    finally:
        loader.close()


if __name__ == '__main__':
    main()
