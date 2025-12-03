"""
Reddit sentiment collector using PRAW
"""
import praw
import os
import pandas as pd
import json
import re
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
import sys
sys.path.append(str(Path(__file__).parent.parent))

from utils.rate_limiter import reddit_limiter
from utils.error_handler import safe_api_call, create_logger
from utils.date_utils import get_date_range

load_dotenv()
logger = create_logger(__name__)


class RedditSentimentCollector:
    """Collector for Reddit sentiment data using PRAW"""
    
    def __init__(self, output_dir='data/raw/reddit'):
        # Load credentials
        self.client_id = os.getenv('REDDIT_CLIENT_ID')
        self.client_secret = os.getenv('REDDIT_CLIENT_SECRET')
        self.user_agent = os.getenv('REDDIT_USER_AGENT')
        
        if not all([self.client_id, self.client_secret, self.user_agent]):
            raise ValueError(
                "Reddit credentials not found. Set REDDIT_CLIENT_ID, "
                "REDDIT_CLIENT_SECRET, and REDDIT_USER_AGENT in .env"
            )
        
        # Initialize Reddit instance
        self.reddit = praw.Reddit(
            client_id=self.client_id,
            client_secret=self.client_secret,
            user_agent=self.user_agent
        )
        
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Subreddits to monitor
        self.subreddits = ['wallstreetbets', 'stocks', 'investing', 'StockMarket']
        
        logger.info(f"Initialized Reddit collector for subreddits: {self.subreddits}")
    
    def extract_tickers(self, text):
        """
        Extract stock ticker mentions from text
        Looks for $TICKER or TICKER patterns
        
        Args:
            text: Post title or body text
        
        Returns:
            List of ticker symbols found
        """
        if not text:
            return []
        
        tickers = []
        
        # Pattern 1: $TICKER format (like Twitter cashtags)
        cashtag_pattern = r'\$([A-Z]{1,5})\b'
        cashtags = re.findall(cashtag_pattern, text)
        tickers.extend(cashtags)
        
        # Pattern 2: TICKER format (all caps, 1-5 letters)
        # But exclude common words
        common_words = {
            'THE', 'FOR', 'AND', 'ARE', 'BUT', 'NOT', 'YOU', 'ALL',
            'CAN', 'HER', 'WAS', 'ONE', 'OUR', 'OUT', 'DAY', 'GET',
            'HAS', 'HIM', 'HIS', 'HOW', 'ITS', 'MAY', 'NEW', 'NOW',
            'OLD', 'SEE', 'TWO', 'WAY', 'WHO', 'BOY', 'DID', 'ILL',
            'LET', 'PUT', 'SAY', 'SHE', 'TOO', 'USE', 'CEO', 'WSB',
            'DD', 'YOLO', 'FOMO', 'IMO', 'TL;DR', 'TLDR', 'ETA', 'ATH'
        }
        
        word_pattern = r'\b([A-Z]{2,5})\b'
        words = re.findall(word_pattern, text)
        
        for word in words:
            if word not in common_words and word not in tickers:
                tickers.append(word)
        
        return list(set(tickers))  # Remove duplicates
    
    def simple_sentiment(self, text, score):
        """
        Simple sentiment analysis based on keywords and score
        
        Args:
            text: Post/comment text
            score: Reddit score (upvotes - downvotes)
        
        Returns:
            Sentiment score between -1 (negative) and 1 (positive)
        """
        if not text:
            return 0.0
        
        text_lower = text.lower()
        
        # Positive keywords
        positive_words = [
            'bull', 'bullish', 'buy', 'long', 'calls', 'moon', 'rocket',
            'up', 'gain', 'profit', 'win', 'beat', 'strong', 'good',
            'great', 'excellent', 'love', 'positive', 'growth', 'surge'
        ]
        
        # Negative keywords
        negative_words = [
            'bear', 'bearish', 'sell', 'short', 'puts', 'crash', 'down',
            'loss', 'lose', 'bad', 'weak', 'poor', 'terrible', 'hate',
            'negative', 'decline', 'drop', 'fall', 'miss', 'warning'
        ]
        
        # Count occurrences
        positive_count = sum(1 for word in positive_words if word in text_lower)
        negative_count = sum(1 for word in negative_words if word in text_lower)
        
        # Calculate base sentiment
        if positive_count + negative_count == 0:
            base_sentiment = 0.0
        else:
            base_sentiment = (positive_count - negative_count) / (positive_count + negative_count)
        
        # Weight by Reddit score (upvotes indicate community agreement)
        # Normalize score between -1 and 1
        if score > 0:
            score_weight = min(score / 100, 1.0)  # Cap at 1.0
        else:
            score_weight = max(score / 100, -1.0)  # Cap at -1.0
        
        # Combine base sentiment with score weight
        final_sentiment = (base_sentiment * 0.7) + (score_weight * 0.3)
        
        return max(-1.0, min(1.0, final_sentiment))  # Clamp to [-1, 1]
    
    @reddit_limiter
    @safe_api_call
    def search_ticker_posts(self, ticker, subreddit_name, time_filter='month', limit=100):
        """
        Search for posts mentioning a ticker in a subreddit
        
        Args:
            ticker: Stock ticker to search
            subreddit_name: Subreddit to search
            time_filter: 'hour', 'day', 'week', 'month', 'year', 'all'
            limit: Maximum posts to retrieve
        
        Returns:
            List of post dictionaries
        """
        logger.info(f"Searching r/{subreddit_name} for {ticker} (time: {time_filter}, limit: {limit})")
        
        subreddit = self.reddit.subreddit(subreddit_name)
        
        # Search for ticker (try both $TICKER and TICKER)
        search_query = f"{ticker} OR ${ticker}"
        
        posts = []
        
        for submission in subreddit.search(search_query, time_filter=time_filter, limit=limit):
            # Extract ticker mentions
            tickers_in_post = self.extract_tickers(submission.title + ' ' + submission.selftext)
            
            # Only include if our ticker is mentioned
            if ticker.upper() in [t.upper() for t in tickers_in_post]:
                # Calculate sentiment
                sentiment = self.simple_sentiment(
                    submission.title + ' ' + submission.selftext,
                    submission.score
                )
                
                post_data = {
                    'post_id': submission.id,
                    'created_utc': datetime.fromtimestamp(submission.created_utc),
                    'title': submission.title,
                    'selftext': submission.selftext[:500],  # Truncate long posts
                    'score': submission.score,
                    'upvote_ratio': submission.upvote_ratio,
                    'num_comments': submission.num_comments,
                    'author': str(submission.author) if submission.author else '[deleted]',
                    'url': submission.url,
                    'tickers': tickers_in_post,
                    'sentiment': sentiment
                }
                
                posts.append(post_data)
        
        logger.info(f"Found {len(posts)} posts mentioning {ticker} in r/{subreddit_name}")
        return posts
    
    def aggregate_daily_sentiment(self, posts, ticker):
        """
        Aggregate posts into daily sentiment metrics
        
        Args:
            posts: List of post dictionaries
            ticker: Stock ticker
        
        Returns:
            DataFrame with daily aggregated sentiment
        """
        if not posts:
            return pd.DataFrame()
        
        df = pd.DataFrame(posts)
        df['date'] = df['created_utc'].dt.date
        
        # Group by date
        daily = df.groupby('date').agg({
            'post_id': 'count',
            'sentiment': 'mean',
            'score': ['mean', 'sum'],
            'num_comments': 'sum'
        }).reset_index()
        
        # Flatten column names
        daily.columns = ['date', 'mention_count', 'avg_sentiment', 'avg_score', 'total_score', 'total_comments']
        
        # Calculate positive/negative counts
        positive_counts = df[df['sentiment'] > 0.1].groupby('date').size()
        negative_counts = df[df['sentiment'] < -0.1].groupby('date').size()
        neutral_counts = df[(df['sentiment'] >= -0.1) & (df['sentiment'] <= 0.1)].groupby('date').size()
        
        daily['positive_count'] = daily['date'].map(positive_counts).fillna(0).astype(int)
        daily['negative_count'] = daily['date'].map(negative_counts).fillna(0).astype(int)
        daily['neutral_count'] = daily['date'].map(neutral_counts).fillna(0).astype(int)
        
        # Add ticker
        daily['ticker'] = ticker
        
        return daily
    
    def save_posts(self, posts, ticker, subreddit_name):
        """Save individual posts to JSON"""
        output_file = self.output_dir / f"{ticker}_{subreddit_name}_posts.json"
        
        # Convert datetime to string for JSON serialization
        posts_serializable = []
        for post in posts:
            post_copy = post.copy()
            post_copy['created_utc'] = post_copy['created_utc'].isoformat()
            posts_serializable.append(post_copy)
        
        with open(output_file, 'w') as f:
            json.dump(posts_serializable, f, indent=2)
        
        logger.info(f"Saved {len(posts)} posts to {output_file}")
    
    def save_daily_sentiment(self, df, ticker, subreddit_name):
        """Save daily aggregated sentiment to CSV"""
        output_file = self.output_dir / f"{ticker}_{subreddit_name}_daily.csv"
        df.to_csv(output_file, index=False)
        logger.info(f"Saved daily sentiment to {output_file}")
    
    def collect_for_ticker(self, ticker, subreddits=None, time_filter='month', 
                          limit_per_subreddit=100, save_posts_detail=True):
        """
        Collect Reddit sentiment for a ticker across multiple subreddits
        
        Args:
            ticker: Stock ticker
            subreddits: List of subreddit names (default: uses self.subreddits)
            time_filter: Time filter for search
            limit_per_subreddit: Max posts per subreddit
            save_posts_detail: Whether to save individual posts
        
        Returns:
            Dictionary with status and aggregated data
        """
        if subreddits is None:
            subreddits = self.subreddits
        
        try:
            all_posts = []
            
            # Collect from each subreddit
            for subreddit in subreddits:
                posts = self.search_ticker_posts(
                    ticker,
                    subreddit,
                    time_filter=time_filter,
                    limit=limit_per_subreddit
                )
                
                # Add subreddit info
                for post in posts:
                    post['subreddit'] = subreddit
                
                all_posts.extend(posts)
                
                # Save individual posts if requested
                if save_posts_detail and posts:
                    self.save_posts(posts, ticker, subreddit)
            
            if not all_posts:
                return {
                    'ticker': ticker,
                    'status': 'no_data',
                    'total_posts': 0
                }
            
            # Aggregate daily sentiment
            daily_sentiment = self.aggregate_daily_sentiment(all_posts, ticker)
            
            # Save aggregated data
            self.save_daily_sentiment(daily_sentiment, ticker, 'combined')
            
            return {
                'ticker': ticker,
                'status': 'success',
                'total_posts': len(all_posts),
                'date_range': {
                    'earliest': daily_sentiment['date'].min().strftime('%Y-%m-%d'),
                    'latest': daily_sentiment['date'].max().strftime('%Y-%m-%d')
                },
                'avg_daily_mentions': daily_sentiment['mention_count'].mean(),
                'avg_sentiment': daily_sentiment['avg_sentiment'].mean(),
                'subreddits': subreddits
            }
            
        except Exception as e:
            logger.error(f"Failed to collect Reddit data for {ticker}: {str(e)}")
            return {
                'ticker': ticker,
                'status': 'failed',
                'error': str(e)
            }
    
    def collect_for_multiple_tickers(self, tickers, time_filter='month', 
                                    limit_per_subreddit=100):
        """
        Collect Reddit sentiment for multiple tickers
        
        Args:
            tickers: List of ticker symbols
            time_filter: Time filter for search
            limit_per_subreddit: Max posts per subreddit
        
        Returns:
            List of results for each ticker
        """
        results = []
        
        for i, ticker in enumerate(tickers, 1):
            logger.info(f"Processing {ticker} ({i}/{len(tickers)})")
            
            result = self.collect_for_ticker(
                ticker,
                time_filter=time_filter,
                limit_per_subreddit=limit_per_subreddit
            )
            results.append(result)
            
            # Progress update
            if i % 3 == 0:
                successful = sum(1 for r in results if r['status'] == 'success')
                logger.info(f"Progress: {i}/{len(tickers)}, {successful} successful")
        
        # Summary
        successful = sum(1 for r in results if r['status'] == 'success')
        failed = sum(1 for r in results if r['status'] == 'failed')
        no_data = sum(1 for r in results if r['status'] == 'no_data')
        
        logger.info(f"Completed: {successful} success, {failed} failed, {no_data} no data")
        
        return results


def main():
    """Example usage"""
    collector = RedditSentimentCollector()
    
    # Test with small batch
    tickers = ['AAPL', 'TSLA', 'GME']
    
    print(f"\nCollecting Reddit sentiment for {len(tickers)} stocks")
    print(f"Subreddits: {collector.subreddits}")
    print(f"Time filter: month\n")
    
    results = collector.collect_for_multiple_tickers(
        tickers,
        time_filter='month',  # Options: 'day', 'week', 'month', 'year'
        limit_per_subreddit=100
    )
    
    # Print summary
    for result in results:
        print(f"\n{result['ticker']}: {result['status']}")
        if result['status'] == 'success':
            print(f"  Total posts: {result['total_posts']}")
            print(f"  Date range: {result['date_range']}")
            print(f"  Avg daily mentions: {result['avg_daily_mentions']:.1f}")
            print(f"  Avg sentiment: {result['avg_sentiment']:.2f}")


if __name__ == '__main__':
    main()