"""
Load News Article data into PostgreSQL database
Processes output from NewsCollector.py

Input files per ticker:
  - {ticker}_articles.csv: Individual articles with sentiment
  - {ticker}_daily_news.csv: Daily aggregated news metrics
  - {ticker}_news_raw_*.json: Raw API responses (optional for validation)
"""
import json
import os
from dotenv import load_dotenv
import pandas as pd
from pathlib import Path
from datetime import datetime
import psycopg2
from psycopg2.extras import execute_batch
import logging
from typing import Dict, Tuple, Optional

load_dotenv()


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class NewsLoader:
    """Load News data from CSV files into PostgreSQL"""
    
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
            'articles_inserted': 0,
            'articles_skipped': 0,
            'tickers_created': 0,
            'tickers_fetched': 0,
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
    
    def load_articles_from_csv(self, csv_path: str, ticker: str) -> pd.DataFrame:
        """
        Load articles from CSV file
        
        Args:
            csv_path: Path to CSV file
            ticker: Stock ticker symbol
        
        Returns:
            DataFrame with articles
        """
        if not Path(csv_path).exists():
            logger.warning(f"File not found: {csv_path}")
            return pd.DataFrame()
        
        df = pd.read_csv(csv_path)
        logger.info(f"Loaded {len(df)} articles from {csv_path}")
        
        # Validate required columns
        required_cols = ['ticker', 'published_date', 'headline', 'source', 'url']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            logger.warning(f"Missing columns in CSV: {missing_cols}")
        
        return df
    
    def insert_article(self, 
                      ticker_id: int,
                      title: str,
                      source: str,
                      url: str,
                      published_at: datetime,
                      description: Optional[str] = None,
                      content: Optional[str] = None,
                      author: Optional[str] = None,
                      word_count: Optional[int] = None) -> Optional[int]:
        """
        Insert a single article into the database
        
        Args:
            ticker_id: Ticker ID
            title: Article headline/title
            source: News source (Yahoo, Bloomberg, etc.)
            url: Article URL
            published_at: Publication date/time
            description: Article summary
            content: Full article content
            author: Article author
            word_count: Word count of content
        
        Returns:
            news_article_id if successful, None if duplicate
        """
        try:
            # Check if URL already exists (avoid duplicates)
            self.cursor.execute(
                "SELECT news_article_id FROM news_articles WHERE url = %s",
                (url,)
            )
            
            if self.cursor.fetchone():
                self.stats['articles_skipped'] += 1
                return None
            
            # Insert article
            self.cursor.execute(
                """
                INSERT INTO news_articles 
                (source, author, title, description, content, url, published_at, retrieved_at, word_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s)
                RETURNING news_article_id
                """,
                (source, author, title, description, content, url, published_at, word_count)
            )
            
            article_id = self.cursor.fetchone()[0]
            self.stats['articles_inserted'] += 1
            
            return article_id
        
        except Exception as e:
            logger.warning(f"Error inserting article '{title[:50]}...': {e}")
            return None
    
    def insert_article_ticker_mapping(self,
                                     news_article_id: int,
                                     ticker_id: int,
                                     mention_count: int = 1,
                                     prominence: Optional[float] = None,
                                     relevance: Optional[float] = None):
        """
        Map article to ticker
        
        Args:
            news_article_id: Article ID
            ticker_id: Ticker ID
            mention_count: Number of mentions
            prominence: Prominence score (0-1)
            relevance: Relevance score (0-1)
        """
        try:
            self.cursor.execute(
                """
                INSERT INTO news_article_tickers 
                (news_article_id, ticker_id, mention_count, prominence, relevance, created_at)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (news_article_id, ticker_id) 
                DO UPDATE SET mention_count = EXCLUDED.mention_count
                """,
                (news_article_id, ticker_id, mention_count, prominence, relevance)
            )
        except Exception as e:
            logger.warning(f"Error mapping article {news_article_id} to ticker {ticker_id}: {e}")
    
    def insert_article_sentiment(self,
                                news_article_id: int,
                                ticker_id: int,
                                sentiment_score: Optional[float] = None,
                                sentiment_label: str = 'neutral',
                                positive_score: Optional[float] = None,
                                negative_score: Optional[float] = None,
                                neutral_score: Optional[float] = None,
                                model_name: str = 'headline_keywords',
                                model_version: str = '1.0'):
        """
        Insert sentiment analysis for article
        
        Args:
            news_article_id: Article ID
            ticker_id: Ticker ID
            sentiment_score: Sentiment score (-1 to 1)
            sentiment_label: Label (positive/negative/neutral)
            positive_score: Positive component score
            negative_score: Negative component score
            neutral_score: Neutral component score
            model_name: Sentiment analysis model name
            model_version: Model version
        """
        try:
            # Convert sentiment score to label if needed
            if sentiment_label == 'neutral' and sentiment_score is not None:
                if sentiment_score > 0.1:
                    sentiment_label = 'positive'
                elif sentiment_score < -0.1:
                    sentiment_label = 'negative'
            
            self.cursor.execute(
                """
                INSERT INTO news_article_sentiment
                (news_article_id, ticker_id, sentiment_label, sentiment_score, 
                 positive_score, negative_score, neutral_score, model_name, model_version, analyzed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (news_article_id, ticker_id) 
                DO UPDATE SET 
                    sentiment_label = EXCLUDED.sentiment_label,
                    sentiment_score = EXCLUDED.sentiment_score,
                    analyzed_at = CURRENT_TIMESTAMP
                """,
                (news_article_id, ticker_id, sentiment_label, sentiment_score,
                 positive_score, negative_score, neutral_score, model_name, model_version)
            )
        except Exception as e:
            logger.warning(f"Error inserting sentiment for article {news_article_id}: {e}")
    
    def load_ticker_articles(self, articles_csv: str, ticker: str, auto_commit: bool = True) -> int:
        """
        Load all articles for a ticker from CSV
        
        Args:
            articles_csv: Path to {ticker}_articles.csv
            ticker: Stock ticker symbol
            auto_commit: Whether to auto-commit changes
        
        Returns:
            Number of articles inserted
        """
        df = self.load_articles_from_csv(articles_csv, ticker)
        
        if df.empty:
            return 0
        
        # Get ticker ID
        ticker_id = self.get_or_create_ticker(ticker)
        
        initial_count = self.stats['articles_inserted']
        
        # Process each article
        for idx, row in df.iterrows():
            try:
                # Parse published date
                published_at = pd.to_datetime(row.get('published_date'))
                
                # Insert article
                article_id = self.insert_article(
                    ticker_id=ticker_id,
                    title=str(row.get('headline', '')),
                    source=str(row.get('source', 'Unknown')),
                    url=str(row.get('url', '')),
                    published_at=published_at,
                    description=str(row.get('summary', '')) if pd.notna(row.get('summary')) else None,
                    author=str(row.get('author', '')) if pd.notna(row.get('author')) else None
                )
                
                if article_id:
                    # Map to ticker
                    self.insert_article_ticker_mapping(
                        article_id,
                        ticker_id,
                        mention_count=1,
                        relevance=1.0  # Articles are directly about the ticker
                    )
                    
                    # Insert sentiment
                    sentiment_score = float(row.get('headline_sentiment', 0.0))
                    self.insert_article_sentiment(
                        article_id,
                        ticker_id,
                        sentiment_score=sentiment_score
                    )
                
                # Batch commit every 100 articles
                if (idx + 1) % 100 == 0:
                    if auto_commit:
                        self.conn.commit()
                        logger.info(f"Committed batch of 100 articles ({idx + 1}/{len(df)})")
            
            except Exception as e:
                logger.error(f"Error processing article at row {idx}: {e}")
                continue
        
        # Final commit
        if auto_commit:
            self.conn.commit()
        
        inserted = self.stats['articles_inserted'] - initial_count
        logger.info(f"✓ Loaded {inserted} new articles for {ticker}")
        
        return inserted
    
    def load_all_tickers(self, data_dir: str = 'data/raw/news', auto_commit: bool = True) -> Dict:
        """
        Load articles for all tickers in the data directory
        
        Args:
            data_dir: Directory containing {ticker}_articles.csv files
            auto_commit: Whether to auto-commit changes
        
        Returns:
            Dictionary with load statistics
        """
        data_path = Path(data_dir)
        
        if not data_path.exists():
            logger.error(f"Data directory not found: {data_dir}")
            return self.stats
        
        # Find all article CSV files
        article_files = sorted(data_path.glob('*_articles.csv'))
        
        if not article_files:
            logger.warning(f"No article files found in {data_dir}")
            return self.stats
        
        logger.info(f"Found {len(article_files)} article files")
        
        # Load each ticker
        for csv_file in article_files:
            try:
                # Extract ticker from filename
                ticker = csv_file.stem.replace('_articles', '')
                logger.info(f"\nLoading articles for {ticker}...")
                
                self.load_ticker_articles(str(csv_file), ticker, auto_commit=auto_commit)
            
            except Exception as e:
                logger.error(f"Failed to load {csv_file}: {e}")
                continue
        
        return self.stats
    
    def print_statistics(self):
        """Print loading statistics"""
        print("\n" + "="*60)
        print("NEWS LOADER STATISTICS")
        print("="*60)
        print(f"Articles inserted:  {self.stats['articles_inserted']:>10}")
        print(f"Articles skipped:   {self.stats['articles_skipped']:>10}")
        print(f"Tickers created:    {self.stats['tickers_created']:>10}")
        print(f"Tickers fetched:    {self.stats['tickers_fetched']:>10}")
        print("="*60 + "\n")


def main():
    """Example usage"""
    # Database parameters
    # Database configuration
    DB_CONFIG = {
        'dbname': os.getenv('DB_NAME'),
        'user': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASSWORD'),
        'host': os.getenv('DB_HOST'),
        'port': os.getenv('DB_PORT')
    }
    
    # Initialize loader
    loader = NewsLoader(DB_CONFIG)
    
    try:
        loader.connect()
        
        # Load all news articles
        print("Loading news articles from data/raw/news/")
        loader.load_all_tickers('data/raw/news')
        
        # Print statistics
        loader.print_statistics()
    
    except Exception as e:
        logger.error(f"Failed to load news data: {e}")
    
    finally:
        loader.close()


if __name__ == '__main__':
    main()
