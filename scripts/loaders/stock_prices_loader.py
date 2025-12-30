"""
Load Stock Price data into PostgreSQL database
Processes output from stock_prices.py collector

Input files per ticker:
  - {ticker}_prices.csv: Historical daily price data
  - {ticker}_info.json: Company information
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


class StockPriceLoader:
    """Load Stock Price data from CSV files into PostgreSQL"""
    
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
            'prices_inserted': 0,
            'prices_skipped': 0,
            'tickers_created': 0,
            'tickers_updated': 0,
            'tickers_fetched': 0
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
    
    def get_or_create_ticker(self, symbol: str, company_info: Optional[Dict] = None) -> int:
        """
        Get ticker_id for a symbol, create if doesn't exist
        Update company info if provided
        Uses cache to minimize database queries
        
        Args:
            symbol: Stock ticker symbol
            company_info: Optional dict with company information
        
        Returns:
            ticker_id (int)
        """
        symbol = symbol.upper()
        
        # Check cache first
        if symbol in self.ticker_cache:
            ticker_id = self.ticker_cache[symbol]
            
            # Update company info if provided
            if company_info:
                self.update_ticker_info(ticker_id, company_info)
            
            return ticker_id
        
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
            
            # Update company info if provided
            if company_info:
                self.update_ticker_info(ticker_id, company_info)
            
            return ticker_id
        
        # Create new ticker
        if company_info:
            self.cursor.execute(
                """
                INSERT INTO tickers (symbol, company_name, sector, industry)
                VALUES (%s, %s, %s, %s)
                RETURNING ticker_id
                """,
                (symbol, 
                 company_info.get('name', ''),
                 company_info.get('sector', ''),
                 company_info.get('industry', ''))
            )
        else:
            self.cursor.execute(
                "INSERT INTO tickers (symbol) VALUES (%s) RETURNING ticker_id",
                (symbol,)
            )
        
        ticker_id = self.cursor.fetchone()[0]
        self.ticker_cache[symbol] = ticker_id
        self.stats['tickers_created'] += 1
        logger.info(f"Created new ticker: {symbol} (ID: {ticker_id})")
        
        return ticker_id
    
    def update_ticker_info(self, ticker_id: int, company_info: Dict):
        """
        Update ticker with company information
        
        Args:
            ticker_id: Ticker ID
            company_info: Dictionary with company info
        """
        try:
            self.cursor.execute(
                """
                UPDATE tickers 
                SET company_name = %s, sector = %s, industry = %s
                WHERE ticker_id = %s
                """,
                (company_info.get('name', ''),
                 company_info.get('sector', ''),
                 company_info.get('industry', ''),
                 ticker_id)
            )
            self.stats['tickers_updated'] += 1
        except Exception as e:
            logger.warning(f"Failed to update ticker {ticker_id}: {e}")
    
    def load_company_info(self, json_file: str) -> Optional[Dict]:
        """
        Load company information from JSON file
        
        Args:
            json_file: Path to {ticker}_info.json
        
        Returns:
            Dictionary with company info or None
        """
        if not Path(json_file).exists():
            return None
        
        try:
            with open(json_file, 'r') as f:
                info = json.load(f)
            return info
        except Exception as e:
            logger.warning(f"Failed to load company info from {json_file}: {e}")
            return None
    
    def load_prices_from_csv(self, csv_file: str, ticker: str) -> pd.DataFrame:
        """
        Load price data from CSV file
        
        Args:
            csv_file: Path to {ticker}_prices.csv
            ticker: Stock ticker symbol
        
        Returns:
            DataFrame with price data
        """
        if not Path(csv_file).exists():
            logger.warning(f"File not found: {csv_file}")
            return pd.DataFrame()
        
        try:
            df = pd.read_csv(csv_file)
            
            # Verify required columns
            required_cols = ['date', 'open', 'high', 'low', 'close', 'volume']
            missing_cols = [col for col in required_cols if col not in df.columns]
            
            if missing_cols:
                logger.warning(f"Missing columns in CSV: {missing_cols}")
                return pd.DataFrame()
            
            logger.info(f"Loaded {len(df)} price records from {Path(csv_file).name}")
            return df
        
        except Exception as e:
            logger.error(f"Failed to load {csv_file}: {e}")
            return pd.DataFrame()
    
    def insert_price(self,
                    ticker_id: int,
                    date: datetime,
                    open_price: float,
                    high: float,
                    low: float,
                    close: float,
                    adj_close: Optional[float],
                    volume: int) -> Optional[int]:
        """
        Insert a single price record into the database
        
        Args:
            ticker_id: Ticker ID
            date: Trading date
            open_price: Opening price
            high: High price
            low: Low price
            close: Closing price
            adj_close: Adjusted closing price
            volume: Trading volume
        
        Returns:
            price_id if successful, None if duplicate or error
        """
        try:
            # Check if price already exists (avoid duplicates)
            self.cursor.execute(
                "SELECT price_id FROM stock_prices WHERE ticker_id = %s AND date = %s",
                (ticker_id, date)
            )
            
            if self.cursor.fetchone():
                self.stats['prices_skipped'] += 1
                return None
            
            # Insert price
            self.cursor.execute(
                """
                INSERT INTO stock_prices 
                (ticker_id, date, open, high, low, close, adj_close, volume)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING price_id
                """,
                (ticker_id, date, open_price, high, low, close, adj_close, volume)
            )
            
            price_id = self.cursor.fetchone()[0]
            self.stats['prices_inserted'] += 1
            
            return price_id
        
        except psycopg2.errors.UniqueViolation:
            # Handle unique constraint violations
            self.conn.rollback()
            self.stats['prices_skipped'] += 1
            return None
        except Exception as e:
            # Rollback transaction on any error to prevent "transaction aborted" errors
            self.conn.rollback()
            logger.warning(f"Error inserting price for {date}: {e}")
            return None
    
    def load_ticker_prices(self, csv_file: str, ticker: str, info_file: Optional[str] = None, 
                          auto_commit: bool = True) -> int:
        """
        Load all prices for a ticker from CSV
        
        Args:
            csv_file: Path to {ticker}_prices.csv
            ticker: Stock ticker symbol
            info_file: Optional path to {ticker}_info.json
            auto_commit: Whether to auto-commit changes
        
        Returns:
            Number of prices inserted
        """
        # Load company info if available
        company_info = None
        if info_file:
            company_info = self.load_company_info(info_file)
        
        # Load price data
        df = self.load_prices_from_csv(csv_file, ticker)
        
        if df.empty:
            return 0
        
        # Get or create ticker
        ticker_id = self.get_or_create_ticker(ticker, company_info)
        
        initial_count = self.stats['prices_inserted']
        
        # Process each price record
        for idx, row in df.iterrows():
            try:
                # Parse date
                try:
                    date = pd.to_datetime(row['date']).date()
                except:
                    logger.warning(f"Could not parse date: {row['date']}")
                    continue
                
                # Get adjusted close (may not be present in all CSVs)
                adj_close = None
                if 'adj_close' in df.columns and pd.notna(row.get('adj_close')):
                    adj_close = float(row['adj_close'])
                
                # Insert price
                self.insert_price(
                    ticker_id=ticker_id,
                    date=date,
                    open_price=float(row['open']),
                    high=float(row['high']),
                    low=float(row['low']),
                    close=float(row['close']),
                    adj_close=adj_close,
                    volume=int(row['volume'])
                )
                
                # Batch commit every 100 prices
                if (idx + 1) % 100 == 0:
                    if auto_commit:
                        self.conn.commit()
                        logger.info(f"Committed batch of 100 prices ({idx + 1}/{len(df)})")
            
            except Exception as e:
                logger.error(f"Error processing price at row {idx}: {e}")
                continue
        
        # Final commit
        if auto_commit:
            self.conn.commit()
        
        inserted = self.stats['prices_inserted'] - initial_count
        logger.info(f"✓ Loaded {inserted} new prices for {ticker}")
        
        return inserted
    
    def load_all_tickers(self, data_dir: str = 'data/raw/prices', auto_commit: bool = True) -> Dict:
        """
        Load prices for all tickers in the data directory
        
        Args:
            data_dir: Directory containing {ticker}_prices.csv files
            auto_commit: Whether to auto-commit changes
        
        Returns:
            Dictionary with load statistics
        """
        data_path = Path(data_dir)
        
        if not data_path.exists():
            logger.error(f"Data directory not found: {data_dir}")
            return self.stats
        
        # Find all price CSV files
        price_files = sorted(data_path.glob('*_prices.csv'))
        
        if not price_files:
            logger.warning(f"No price files found in {data_dir}")
            return self.stats
        
        logger.info(f"Found {len(price_files)} price files")
        
        # Load each ticker
        for csv_file in price_files:
            try:
                # Extract ticker from filename
                ticker = csv_file.stem.replace('_prices', '')
                logger.info(f"\nLoading prices for {ticker}...")
                
                # Check for corresponding info file
                info_file = data_path / f"{ticker}_info.json"
                info_file_path = str(info_file) if info_file.exists() else None
                
                self.load_ticker_prices(
                    str(csv_file), 
                    ticker, 
                    info_file=info_file_path,
                    auto_commit=auto_commit
                )
            
            except Exception as e:
                logger.error(f"Failed to load {csv_file}: {e}")
                continue
        
        return self.stats
    
    def print_statistics(self):
        """Print loading statistics"""
        print("\n" + "="*60)
        print("STOCK PRICE LOADER STATISTICS")
        print("="*60)
        print(f"Prices inserted:           {self.stats['prices_inserted']:7d}")
        print(f"Prices skipped:            {self.stats['prices_skipped']:7d}")
        print(f"Tickers created:           {self.stats['tickers_created']:7d}")
        print(f"Tickers updated:           {self.stats['tickers_updated']:7d}")
        print(f"Tickers fetched:           {self.stats['tickers_fetched']:7d}")
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
    
    loader = StockPriceLoader(db_params)
    
    try:
        # Connect to database
        loader.connect()
        
        # Load all ticker prices
        print("\nLoading stock prices from data/raw/prices/")
        print("CSV columns: date, open, high, low, close, volume")
        print()
        
        loader.load_all_tickers(
            data_dir='data/raw/prices',
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
