"""
Load Reddit sentiment data into PostgreSQL database
Processes output from RedditSentimentCollector.py

Input files per ticker:
  - {ticker}_posts.json: Individual posts with sentiment
  - {ticker}_daily.csv: Daily aggregated sentiment metrics
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
import hashlib

load_dotenv()  # Load environment variables from .env file if present


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RedditLoader:
    """Load Reddit data from local files into PostgreSQL"""
    
    def __init__(self, db_params):
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
    
    def get_or_create_ticker(self, symbol):
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
        self.conn.commit()
        
        self.ticker_cache[symbol] = ticker_id
        logger.info(f"  Created new ticker: {symbol} (id: {ticker_id})")
        
        return ticker_id
    
    def generate_post_id(self, post_data):
        """
        Generate a unique post_id from post data
        Uses hash of URL or title+timestamp if URL not available
        """
        # If URL exists and looks like a Reddit URL, extract ID
        url = post_data.get('url', '') or post_data.get('link', '')
        if url and 'reddit.com' in url:
            # Extract Reddit post ID from URL (format: /comments/{post_id}/)
            parts = url.split('/')
            try:
                comments_idx = parts.index('comments')
                if comments_idx + 1 < len(parts):
                    reddit_id = parts[comments_idx + 1]
                    # Ensure it fits in 20 chars - use hash if too long
                    if len(reddit_id) <= 20:
                        return reddit_id
                    else:
                        # Hash long Reddit IDs
                        hash_val = hashlib.md5(reddit_id.encode()).hexdigest()[:20]
                        return hash_val
            except (ValueError, IndexError):
                pass
        
        # Fallback: hash of title + timestamp
        hash_input = f"{post_data.get('title', '')}_{post_data.get('created_utc', '')}"
        hash_val = hashlib.md5(hash_input.encode()).hexdigest()[:20]
        return f"gen_{hash_val}"[:20]  # Ensure "gen_" prefix doesn't exceed limit
    
    def load_posts_from_json(self, json_file, ticker):
        """
        Load individual Reddit posts from JSON file
        
        Args:
            json_file: Path to {ticker}_posts.json
            ticker: Stock symbol
        
        Returns:
            Dict with loading stats
        """
        logger.info(f"Loading posts from {json_file.name}")
        
        # Get ticker_id
        ticker_id = self.get_or_create_ticker(ticker)
        
        # Load JSON
        try:
            with open(json_file, 'r') as f:
                posts = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load JSON: {e}")
            return {'posts_loaded': 0, 'sentiments_loaded': 0, 'error': str(e)}
        
        if not posts:
            logger.warning(f"No posts found in {json_file}")
            return {'posts_loaded': 0, 'sentiments_loaded': 0}
        
        # Prepare batch inserts
        post_values = []
        post_id_map = {}  # Map generated post_id to index for later reference
        
        for i, post in enumerate(posts):
            post_id = self.generate_post_id(post)
            
            # Parse timestamp (handle ISO format)
            try:
                created_utc = datetime.fromisoformat(
                    post['created_utc'].replace('Z', '+00:00')
                )
            except:
                logger.warning(f"Could not parse timestamp: {post.get('created_utc')}")
                continue
            
            post_values.append((
                post_id,
                'wallstreetbets',  # Default, update if you track subreddit
                post.get('author', '[deleted]')[:100],
                post.get('title', '')[:1000],
                post.get('text', '')[:5000],
                post.get('url', post.get('link', ''))[:500],
                post.get('score', 0),
                None,  # upvote_ratio
                None,  # num_comments
                created_utc
            ))
            
            post_id_map[post_id] = {
                'sentiment': post.get('sentiment', 0.0),
                'tickers': post.get('tickers', [ticker])
            }
        
        # Batch insert posts
        if post_values:
            insert_posts_query = """
                INSERT INTO reddit_posts 
                (post_id, subreddit, author, title, selftext, url, score, 
                 upvote_ratio, num_comments, created_utc)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (post_id) DO NOTHING
            """
            
            try:
                execute_batch(self.cursor, insert_posts_query, post_values, page_size=500)
                self.conn.commit()
                logger.info(f"  Inserted {len(post_values)} posts")
            except Exception as e:
                logger.error(f"Error inserting posts: {e}")
                self.conn.rollback()
                return {'posts_loaded': 0, 'sentiments_loaded': 0, 'error': str(e)}
        
        # Now insert ticker mappings and sentiment
        sentiment_count = 0
        
        for post_id, post_meta in post_id_map.items():
            # Get the reddit_post_id from database
            self.cursor.execute(
                "SELECT reddit_post_id FROM reddit_posts WHERE post_id = %s",
                (post_id,)
            )
            result = self.cursor.fetchone()
            
            if not result:
                continue
            
            reddit_post_id = result[0]
            
            # Insert ticker mapping
            try:
                self.cursor.execute(
                    """
                    INSERT INTO reddit_post_tickers (reddit_post_id, ticker_id, mention_count)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (reddit_post_id, ticker_id) DO NOTHING
                    """,
                    (reddit_post_id, ticker_id, 1)
                )
            except Exception as e:
                logger.warning(f"Error inserting ticker mapping: {e}")
            
            # Insert sentiment
            sentiment_score = post_meta['sentiment']
            sentiment_label = (
                'positive' if sentiment_score > 0.1 
                else 'negative' if sentiment_score < -0.1 
                else 'neutral'
            )
            
            try:
                self.cursor.execute(
                    """
                    INSERT INTO reddit_post_sentiment 
                    (reddit_post_id, ticker_id, sentiment_label, sentiment_score, 
                     model_name, model_version, analyzed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (reddit_post_id, ticker_id) 
                    DO UPDATE SET 
                        sentiment_score = EXCLUDED.sentiment_score,
                        sentiment_label = EXCLUDED.sentiment_label,
                        analyzed_at = CURRENT_TIMESTAMP
                    """,
                    (reddit_post_id, ticker_id, sentiment_label, sentiment_score,
                     'keyword_based', 'v1.0')
                )
                sentiment_count += 1
            except Exception as e:
                logger.warning(f"Error inserting sentiment: {e}")
        
        self.conn.commit()
        logger.info(f"  Inserted sentiment for {sentiment_count} posts")
        
        return {
            'posts_loaded': len(post_values),
            'sentiments_loaded': sentiment_count
        }
    
    def load_daily_sentiment_from_csv(self, csv_file, ticker):
        """
        Load daily aggregated sentiment from CSV
        Creates events in the events table for significant activity
        
        Args:
            csv_file: Path to {ticker}_daily.csv
            ticker: Stock symbol
        
        Returns:
            Dict with loading stats
        """
        logger.info(f"Loading daily sentiment from {csv_file.name}")
        
        # Get ticker_id
        ticker_id = self.get_or_create_ticker(ticker)
        
        # Load CSV
        try:
            df = pd.read_csv(csv_file)
        except Exception as e:
            logger.error(f"Failed to load CSV: {e}")
            return {'events_created': 0, 'error': str(e)}
        
        if df.empty:
            logger.warning(f"No data in {csv_file}")
            return {'events_created': 0}
        
        # Get event_type_id for reddit sentiment
        event_type_id = self.ensure_event_type_exists()
        
        # Prepare events for significant activity days
        event_values = []
        
        for _, row in df.iterrows():
            # Create event if:
            # - High mention volume (>= 5 mentions) OR
            # - Extreme sentiment (|sentiment| > 0.5)
            if row['mention_count'] >= 5 or abs(row['avg_sentiment']) > 0.5:
                
                # Parse date
                try:
                    event_date = pd.to_datetime(row['date'])
                except:
                    logger.warning(f"Could not parse date: {row['date']}")
                    continue
                
                direction = 'positive' if row['avg_sentiment'] > 0 else 'negative'
                
                event_values.append((
                    ticker_id,
                    event_type_id,
                    event_date,
                    row['mention_count'],  # magnitude
                    direction,
                    abs(row['avg_sentiment']),  # confidence
                    None,  # source_id
                    'reddit_daily',  # source_table
                    f"{int(row['mention_count'])} mentions (↑{int(row.get('positive_count', 0))} "
                    f"↓{int(row.get('negative_count', 0))} ~{int(row.get('neutral_count', 0))}), "
                    f"avg sentiment: {row['avg_sentiment']:.2f}"
                ))
        
        # Insert events
        if event_values:
            insert_events_query = """
                INSERT INTO events 
                (ticker_id, event_type_id, event_timestamp, magnitude, direction, 
                 confidence, source_id, source_table, description)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            try:
                execute_batch(self.cursor, insert_events_query, event_values, page_size=500)
                self.conn.commit()
                logger.info(f"  Created {len(event_values)} events")
            except Exception as e:
                logger.error(f"Error inserting events: {e}")
                self.conn.rollback()
                return {'events_created': 0, 'error': str(e)}
        
        return {'events_created': len(event_values)}
    
    def load_ticker_data(self, data_dir, ticker, load_posts=True, load_daily=True):
        """
        Load all Reddit data for a single ticker
        
        Args:
            data_dir: Directory containing the JSON/CSV files
            ticker: Stock symbol
            load_posts: Whether to load individual posts
            load_daily: Whether to load daily aggregated data
        
        Returns:
            Dict with loading stats
        """
        data_dir = Path(data_dir)
        ticker = ticker.upper()
        
        stats = {
            'ticker': ticker,
            'posts_loaded': 0,
            'sentiments_loaded': 0,
            'events_created': 0,
            'status': 'success'
        }
        
        try:
            # Load individual posts
            if load_posts:
                posts_file = data_dir / f"{ticker}_posts.json"
                if posts_file.exists():
                    post_stats = self.load_posts_from_json(posts_file, ticker)
                    stats['posts_loaded'] = post_stats.get('posts_loaded', 0)
                    stats['sentiments_loaded'] = post_stats.get('sentiments_loaded', 0)
                    
                    if 'error' in post_stats:
                        stats['warnings'] = [f"Posts: {post_stats['error']}"]
                else:
                    logger.warning(f"Posts file not found: {posts_file}")
                    stats['warnings'] = [f"Posts file not found"]
            
            # Load daily sentiment
            if load_daily:
                daily_file = data_dir / f"{ticker}_daily.csv"
                if daily_file.exists():
                    daily_stats = self.load_daily_sentiment_from_csv(daily_file, ticker)
                    stats['events_created'] = daily_stats.get('events_created', 0)
                    
                    if 'error' in daily_stats:
                        if 'warnings' not in stats:
                            stats['warnings'] = []
                        stats['warnings'].append(f"Daily: {daily_stats['error']}")
                else:
                    logger.warning(f"Daily file not found: {daily_file}")
                    if 'warnings' not in stats:
                        stats['warnings'] = []
                    stats['warnings'].append(f"Daily file not found")
            
        except Exception as e:
            logger.error(f"Error loading {ticker}: {str(e)}")
            stats['status'] = 'error'
            stats['error'] = str(e)
        
        return stats
    
    def load_multiple_tickers(self, data_dir, tickers, load_posts=True, load_daily=True):
        """
        Load Reddit data for multiple tickers
        
        Args:
            data_dir: Directory containing the data files
            tickers: List of ticker symbols
            load_posts: Whether to load individual posts
            load_daily: Whether to load daily aggregated data
        
        Returns:
            List of stats dicts for each ticker
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"LOADING REDDIT DATA FOR {len(tickers)} TICKERS")
        logger.info(f"{'='*60}")
        logger.info(f"Data directory: {data_dir}")
        logger.info(f"Load posts: {load_posts}")
        logger.info(f"Load daily: {load_daily}\n")
        
        self.connect()
        
        results = []
        
        for i, ticker in enumerate(tickers, 1):
            logger.info(f"[{i}/{len(tickers)}] Processing {ticker}")
            
            stats = self.load_ticker_data(data_dir, ticker, load_posts, load_daily)
            results.append(stats)
            
            # Progress summary every 5 tickers
            if i % 5 == 0:
                successful = sum(1 for r in results if r['status'] == 'success')
                logger.info(f"  Progress: {successful}/{i} successful")
        
        self.close()
        
        # Final summary
        successful = sum(1 for r in results if r['status'] == 'success')
        total_posts = sum(r.get('posts_loaded', 0) for r in results)
        total_sentiments = sum(r.get('sentiments_loaded', 0) for r in results)
        total_events = sum(r.get('events_created', 0) for r in results)
        
        logger.info(f"\n{'='*60}")
        logger.info(f"LOADING COMPLETE")
        logger.info(f"{'='*60}")
        logger.info(f"Successful: {successful}/{len(tickers)}")
        logger.info(f"Total posts loaded: {total_posts}")
        logger.info(f"Total sentiments loaded: {total_sentiments}")
        logger.info(f"Total events created: {total_events}")
        
        return results
    
    def verify_loading(self, ticker):
        """
        Verify that data was loaded correctly for a ticker
        
        Args:
            ticker: Stock symbol
        
        Returns:
            Dict with verification stats
        """
        self.connect()
        
        ticker_id = self.get_or_create_ticker(ticker)
        
        # Count posts
        self.cursor.execute(
            """
            SELECT COUNT(DISTINCT rp.reddit_post_id)
            FROM reddit_posts rp
            JOIN reddit_post_tickers rpt ON rp.reddit_post_id = rpt.reddit_post_id
            WHERE rpt.ticker_id = %s
            """,
            (ticker_id,)
        )
        post_count = self.cursor.fetchone()[0]
        
        # Count sentiments
        self.cursor.execute(
            "SELECT COUNT(*) FROM reddit_post_sentiment WHERE ticker_id = %s",
            (ticker_id,)
        )
        sentiment_count = self.cursor.fetchone()[0]
        
        # Count events
        self.cursor.execute(
            "SELECT COUNT(*) FROM events WHERE ticker_id = %s AND source_table = 'reddit_daily'",
            (ticker_id,)
        )
        event_count = self.cursor.fetchone()[0]
        
        # Date range
        self.cursor.execute(
            """
            SELECT MIN(rp.created_utc), MAX(rp.created_utc)
            FROM reddit_posts rp
            JOIN reddit_post_tickers rpt ON rp.reddit_post_id = rpt.reddit_post_id
            WHERE rpt.ticker_id = %s
            """,
            (ticker_id,)
        )
        date_range = self.cursor.fetchone()
        
        self.close()
        
        return {
            'ticker': ticker,
            'posts': post_count,
            'sentiments': sentiment_count,
            'events': event_count,
            'date_range': {
                'start': date_range[0].strftime('%Y-%m-%d') if date_range[0] else None,
                'end': date_range[1].strftime('%Y-%m-%d') if date_range[1] else None
            }
        }
    
    def ensure_event_type_exists(self):
        """
        Ensure the reddit_sentiment_spike event type exists
        Creates it if not found
        
        Returns:
            event_type_id (int)
        """
        self.cursor.execute(
            "SELECT event_type_id FROM event_types WHERE event_type_name = 'reddit_sentiment_spike'"
        )
        result = self.cursor.fetchone()
        
        if result:
            return result[0]
        
        # Create the event type
        self.cursor.execute(
            """
            INSERT INTO event_types (event_type_name, description)
            VALUES (%s, %s)
            RETURNING event_type_id
            """,
            ('reddit_sentiment_spike', 'Significant Reddit sentiment activity detected')
        )
        event_type_id = self.cursor.fetchone()[0]
        self.conn.commit()
        
        logger.info(f"  Created event type 'reddit_sentiment_spike' (id: {event_type_id})")
        
        return event_type_id


def main():
    """Example usage"""
    
    # Database configuration
    DB_CONFIG = {
        'dbname': os.getenv('DB_NAME'),
        'user': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASSWORD'),
        'host': os.getenv('DB_HOST'),
        'port': os.getenv('DB_PORT')
    }

    
    # Initialize loader
    loader = RedditLoader(DB_CONFIG)
    
    # Test with one ticker first
    print("\n" + "="*60)
    print("TEST: Loading single ticker")
    print("="*60)
    
    test_ticker = 'AAPL'
    data_dir = 'data/processed/reddit-sentiment'  # Updated path
    
    loader.connect()
    result = loader.load_ticker_data(data_dir, test_ticker)
    loader.close()
    
    print(f"\n{test_ticker} Result:")
    print(f"  Status: {result['status']}")
    print(f"  Posts loaded: {result['posts_loaded']}")
    print(f"  Sentiments loaded: {result['sentiments_loaded']}")
    print(f"  Events created: {result['events_created']}")
    
    # Verify
    verification = loader.verify_loading(test_ticker)
    print(f"\nVerification:")
    print(f"  Posts in DB: {verification['posts']}")
    print(f"  Sentiments in DB: {verification['sentiments']}")
    print(f"  Events in DB: {verification['events']}")
    print(f"  Date range: {verification['date_range']['start']} to {verification['date_range']['end']}")
    
    # If test successful, load all tickers
    proceed = input("\nTest successful. Load all tickers? (y/n): ")
    
    if proceed.lower() == 'y':
        tickers = ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'QQQ', 'META', 'TSLA', 'JPM', 'SPY', 'GOOGL', 'AMD', 'IWM']  # Add your full list
        
        results = loader.load_multiple_tickers(
            data_dir=data_dir,
            tickers=tickers,
            load_posts=True,
            load_daily=True
        )
        
        # Print summary
        print("\n" + "="*60)
        print("RESULTS SUMMARY")
        print("="*60)
        for result in results:
            print(f"\n{result['ticker']}: {result['status']}")
            if result['status'] == 'success':
                print(f"  Posts: {result['posts_loaded']}")
                print(f"  Sentiments: {result['sentiments_loaded']}")
                print(f"  Events: {result['events_created']}")
                if 'warnings' in result:
                    print(f"  Warnings: {', '.join(result['warnings'])}")
            elif result['status'] == 'error':
                print(f"  Error: {result['error']}")


if __name__ == '__main__':
    main()