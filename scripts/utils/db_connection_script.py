"""
Database connection and utility functions for stock_events database
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
import os
from typing import List, Dict, Any
from dotenv import load_dotenv
import os



# Database configuration
DB_CONFIG = {
    'dbname': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'host': os.getenv('DB_HOST'),
    'port': os.getenv('DB_PORT')
}

# Alternative: Use environment variables (more secure)
# DB_CONFIG = {
#     'dbname': os.getenv('DB_NAME', 'stock_events'),
#     'user': os.getenv('DB_USER', 'postgres'),
#     'password': os.getenv('DB_PASSWORD'),
#     'host': os.getenv('DB_HOST', 'localhost'),
#     'port': os.getenv('DB_PORT', '5432')
# }


@contextmanager
def get_db_connection():
    """
    Context manager for database connections.
    Automatically handles connection cleanup.
    
    Usage:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tickers")
    """
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        yield conn
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            conn.close()


def execute_query(query: str, params: tuple = None, fetch: bool = True) -> List[Dict[str, Any]]:
    """
    Execute a SQL query and return results as list of dictionaries.
    
    Args:
        query: SQL query string
        params: Query parameters (for parameterized queries)
        fetch: Whether to fetch results (False for INSERT/UPDATE/DELETE)
    
    Returns:
        List of dictionaries (if fetch=True), else None
    """
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(query, params)
        
        if fetch:
            return [dict(row) for row in cursor.fetchall()]
        return None


def insert_ticker(symbol: str, company_name: str = None, sector: str = None, 
                  industry: str = None, cik: str = None) -> int:
    """
    Insert a new ticker into the database.
    
    Args:
        symbol: Stock ticker symbol (e.g., 'AAPL')
        company_name: Full company name
        sector: Business sector
        industry: Industry classification
        cik: SEC Central Index Key
    
    Returns:
        ticker_id of the inserted ticker
    """
    query = """
        INSERT INTO tickers (symbol, company_name, sector, industry, cik)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (symbol) DO UPDATE 
        SET company_name = EXCLUDED.company_name,
            sector = EXCLUDED.sector,
            industry = EXCLUDED.industry,
            cik = EXCLUDED.cik,
            updated_at = CURRENT_TIMESTAMP
        RETURNING ticker_id
    """
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (symbol, company_name, sector, industry, cik))
        ticker_id = cursor.fetchone()[0]
        return ticker_id


def get_ticker_id(symbol: str) -> int:
    """
    Get ticker_id for a given symbol.
    
    Args:
        symbol: Stock ticker symbol
    
    Returns:
        ticker_id, or None if not found
    """
    query = "SELECT ticker_id FROM tickers WHERE symbol = %s"
    result = execute_query(query, (symbol,))
    return result[0]['ticker_id'] if result else None


def insert_reddit_post(post_data: dict) -> int:
    """
    Insert a Reddit post into the database.
    
    Args:
        post_data: Dictionary with post information
            Required: post_id, subreddit, created_utc
            Optional: author, title, selftext, url, score, upvote_ratio, num_comments
    
    Returns:
        reddit_post_id of the inserted post
    """
    query = """
        INSERT INTO reddit_posts 
        (post_id, subreddit, author, title, selftext, url, score, upvote_ratio, num_comments, created_utc)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (post_id) DO NOTHING
        RETURNING reddit_post_id
    """
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (
            post_data['post_id'],
            post_data['subreddit'],
            post_data.get('author'),
            post_data.get('title'),
            post_data.get('selftext'),
            post_data.get('url'),
            post_data.get('score'),
            post_data.get('upvote_ratio'),
            post_data.get('num_comments'),
            post_data['created_utc']
        ))
        result = cursor.fetchone()
        return result[0] if result else None


def link_post_to_ticker(reddit_post_id: int, ticker_id: int, mention_count: int = 1) -> int:
    """
    Create a mapping between a Reddit post and a ticker.
    
    Args:
        reddit_post_id: ID of the Reddit post
        ticker_id: ID of the ticker
        mention_count: Number of times ticker was mentioned
    
    Returns:
        mapping_id
    """
    query = """
        INSERT INTO reddit_post_tickers (reddit_post_id, ticker_id, mention_count)
        VALUES (%s, %s, %s)
        ON CONFLICT (reddit_post_id, ticker_id) DO UPDATE
        SET mention_count = EXCLUDED.mention_count
        RETURNING mapping_id
    """
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (reddit_post_id, ticker_id, mention_count))
        return cursor.fetchone()[0]


def insert_sentiment(reddit_post_id: int, ticker_id: int, sentiment_data: dict) -> int:
    """
    Insert sentiment analysis results for a Reddit post.
    
    Args:
        reddit_post_id: ID of the Reddit post
        ticker_id: ID of the ticker
        sentiment_data: Dictionary with sentiment scores
            Required: sentiment_score, sentiment_label
            Optional: positive_score, negative_score, neutral_score, model_name, model_version
    
    Returns:
        sentiment_id
    """
    query = """
        INSERT INTO reddit_post_sentiment 
        (reddit_post_id, ticker_id, sentiment_score, sentiment_label,
         positive_score, negative_score, neutral_score, model_name, model_version)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (reddit_post_id, ticker_id) DO UPDATE
        SET sentiment_score = EXCLUDED.sentiment_score,
            sentiment_label = EXCLUDED.sentiment_label,
            positive_score = EXCLUDED.positive_score,
            negative_score = EXCLUDED.negative_score,
            neutral_score = EXCLUDED.neutral_score,
            analyzed_at = CURRENT_TIMESTAMP
        RETURNING sentiment_id
    """
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (
            reddit_post_id,
            ticker_id,
            sentiment_data['sentiment_score'],
            sentiment_data['sentiment_label'],
            sentiment_data.get('positive_score'),
            sentiment_data.get('negative_score'),
            sentiment_data.get('neutral_score'),
            sentiment_data.get('model_name', 'VADER'),
            sentiment_data.get('model_version', '3.3.2')
        ))
        return cursor.fetchone()[0]


def get_unprocessed_posts(limit: int = 100) -> List[Dict[str, Any]]:
    """
    Get Reddit posts that haven't had sentiment analysis yet.
    
    Args:
        limit: Maximum number of posts to return
    
    Returns:
        List of post dictionaries
    """
    query = """
        SELECT 
            rp.reddit_post_id,
            rp.post_id,
            rp.title,
            rp.selftext,
            rpt.ticker_id,
            t.symbol
        FROM reddit_posts rp
        JOIN reddit_post_tickers rpt ON rp.reddit_post_id = rpt.reddit_post_id
        JOIN tickers t ON rpt.ticker_id = t.ticker_id
        LEFT JOIN reddit_post_sentiment rps ON rp.reddit_post_id = rps.reddit_post_id 
                                             AND rpt.ticker_id = rps.ticker_id
        WHERE rps.sentiment_id IS NULL
        LIMIT %s
    """
    
    return execute_query(query, (limit,))


def test_connection():
    """Test database connection and display basic info."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Test connection
            cursor.execute("SELECT version();")
            version = cursor.fetchone()[0]
            print(f"✓ Connected to PostgreSQL: {version}\n")
            
            # Count tables
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                ORDER BY table_name
            """)
            tables = cursor.fetchall()
            print(f"✓ Found {len(tables)} tables:")
            for table in tables:
                print(f"  - {table[0]}")
            
            # Count tickers
            cursor.execute("SELECT COUNT(*) FROM tickers")
            ticker_count = cursor.fetchone()[0]
            print(f"\n✓ Database contains {ticker_count} tickers")
            
            # Count posts
            cursor.execute("SELECT COUNT(*) FROM reddit_posts")
            post_count = cursor.fetchone()[0]
            print(f"✓ Database contains {post_count} Reddit posts")
            
            print("\n✓ Connection test successful!")
            
    except Exception as e:
        print(f"✗ Connection failed: {e}")


if __name__ == "__main__":
    # Run test when script is executed directly
    test_connection()