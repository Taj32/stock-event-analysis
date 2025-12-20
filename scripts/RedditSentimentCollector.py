"""
Reddit sentiment collector using CSV data dumps
"""
import pandas as pd
import json
import re
from pathlib import Path
from datetime import datetime
import sys
sys.path.append(str(Path(__file__).parent.parent))

from utils.error_handler import create_logger
from utils.date_utils import get_date_range

logger = create_logger(__name__)


class RedditSentimentCollector:
    """Collector for Reddit sentiment data from CSV dumps"""
    
    def __init__(self, csv_dir='data/raw/reddit_dumps', output_dir='data/raw/reddit'):
        """
        Initialize collector
        
        Args:
            csv_dir: Directory containing monthly CSV dumps
            output_dir: Directory to save processed results
        """
        self.csv_dir = Path(csv_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Target subreddits (case-insensitive matching)
        self.subreddits = ['wallstreetbets', 'stocks', 'investing', 'stockmarket']
        
        logger.info(f"Initialized Reddit collector from CSV dumps in: {self.csv_dir}")
        logger.info(f"Target subreddits: {self.subreddits}")
    
    def load_csv_files(self):
        """
        Load all CSV files from the data dump directory
        
        Returns:
            Combined DataFrame with all posts
        """
        csv_files = sorted(self.csv_dir.glob('*.csv'))
        
        if not csv_files:
            raise ValueError(f"No CSV files found in {self.csv_dir}")
        
        logger.info(f"Found {len(csv_files)} CSV files to process")
        
        dfs = []
        for csv_file in csv_files:
            logger.info(f"Loading {csv_file.name}...")
            df = pd.read_csv(csv_file)
            dfs.append(df)
        
        combined_df = pd.concat(dfs, ignore_index=True)
        logger.info(f"Loaded {len(combined_df):,} total posts from CSV dumps")
        
        return combined_df
    
    def extract_tickers(self, text):
        """
        Extract stock ticker mentions from text
        Looks for $TICKER or TICKER patterns
        
        Args:
            text: Post title or body text
        
        Returns:
            List of ticker symbols found
        """
        if not text or pd.isna(text):
            return []
        
        text = str(text)
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
            'DD', 'YOLO', 'FOMO', 'IMO', 'TLDR', 'ETA', 'ATH', 'IMO',
            'EDIT', 'INFO', 'ALSO', 'JUST', 'LIKE', 'WILL', 'THIS',
            'THAN', 'THAT', 'WITH', 'FROM', 'HAVE', 'MORE', 'BEEN',
            'WERE', 'THEY', 'WHAT', 'THAN', 'WHEN', 'YOUR', 'WILL'
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
        if not text or pd.isna(text):
            return 0.0
        
        text_lower = str(text).lower()
        
        # Positive keywords
        positive_words = [
            'bull', 'bullish', 'buy', 'long', 'calls', 'moon', 'rocket',
            'up', 'gain', 'profit', 'win', 'beat', 'strong', 'good',
            'great', 'excellent', 'love', 'positive', 'growth', 'surge',
            'rally', 'soar', 'breakout'
        ]
        
        # Negative keywords
        negative_words = [
            'bear', 'bearish', 'sell', 'short', 'puts', 'crash', 'down',
            'loss', 'lose', 'bad', 'weak', 'poor', 'terrible', 'hate',
            'negative', 'decline', 'drop', 'fall', 'miss', 'warning',
            'dump', 'tank', 'collapse'
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
    
    def process_posts_for_ticker(self, df, ticker):
        """
        Process all posts mentioning a specific ticker
        
        Args:
            df: DataFrame with all posts
            ticker: Stock ticker to filter for
        
        Returns:
            List of post dictionaries
        """
        logger.info(f"Processing posts for {ticker}...")
        
        posts = []
        
        for idx, row in df.iterrows():
            # Combine title and text for analysis
            title = str(row['title']) if not pd.isna(row['title']) else ''
            text = str(row['text']) if not pd.isna(row['text']) else ''
            combined_text = title + ' ' + text
            
            # Extract tickers from this post
            tickers_in_post = self.extract_tickers(combined_text)
            
            # Only include if our ticker is mentioned
            if ticker.upper() in [t.upper() for t in tickers_in_post]:
                # Calculate sentiment
                sentiment = self.simple_sentiment(combined_text, row['score'])
                
                # Parse date (handle different formats)
                try:
                    created_dt = pd.to_datetime(row['created'])
                except:
                    logger.warning(f"Could not parse date: {row['created']}")
                    continue
                
                post_data = {
                    'created_utc': created_dt,
                    'title': title,
                    'text': text[:500],  # Truncate long text
                    'score': int(row['score']),
                    'author': str(row['author']) if not pd.isna(row['author']) else '[deleted]',
                    'url': str(row['url']) if not pd.isna(row['url']) else '',
                    'link': str(row['link']) if not pd.isna(row['link']) else '',
                    'tickers': tickers_in_post,
                    'sentiment': sentiment
                }
                
                posts.append(post_data)
        
        logger.info(f"Found {len(posts)} posts mentioning {ticker}")
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
        df['date'] = pd.to_datetime(df['created_utc']).dt.date
        
        # Group by date
        daily = df.groupby('date').agg({
            'title': 'count',  # Use title for count
            'sentiment': 'mean',
            'score': ['mean', 'sum']
        }).reset_index()
        
        # Flatten column names
        daily.columns = ['date', 'mention_count', 'avg_sentiment', 'avg_score', 'total_score']
        
        # Calculate positive/negative counts
        positive_counts = df[df['sentiment'] > 0.1].groupby('date').size()
        negative_counts = df[df['sentiment'] < -0.1].groupby('date').size()
        neutral_counts = df[(df['sentiment'] >= -0.1) & (df['sentiment'] <= 0.1)].groupby('date').size()
        
        daily['positive_count'] = daily['date'].map(positive_counts).fillna(0).astype(int)
        daily['negative_count'] = daily['date'].map(negative_counts).fillna(0).astype(int)
        daily['neutral_count'] = daily['date'].map(neutral_counts).fillna(0).astype(int)
        
        # Add ticker
        daily['ticker'] = ticker
        
        # Sort by date
        daily = daily.sort_values('date').reset_index(drop=True)
        
        return daily
    
    def save_posts(self, posts, ticker):
        """Save individual posts to JSON"""
        output_file = self.output_dir / f"{ticker}_posts.json"
        
        # Convert datetime to string for JSON serialization
        posts_serializable = []
        for post in posts:
            post_copy = post.copy()
            post_copy['created_utc'] = post_copy['created_utc'].isoformat()
            posts_serializable.append(post_copy)
        
        with open(output_file, 'w') as f:
            json.dump(posts_serializable, f, indent=2)
        
        logger.info(f"Saved {len(posts)} posts to {output_file}")
    
    def save_daily_sentiment(self, df, ticker):
        """Save daily aggregated sentiment to CSV"""
        output_file = self.output_dir / f"{ticker}_daily.csv"
        df.to_csv(output_file, index=False)
        logger.info(f"Saved daily sentiment to {output_file}")
    
    def collect_for_ticker(self, ticker, all_posts_df, save_posts_detail=True):
        """
        Collect Reddit sentiment for a ticker
        
        Args:
            ticker: Stock ticker
            all_posts_df: DataFrame with all posts from CSV dumps
            save_posts_detail: Whether to save individual posts
        
        Returns:
            Dictionary with status and aggregated data
        """
        try:
            # Process posts for this ticker
            posts = self.process_posts_for_ticker(all_posts_df, ticker)
            
            if not posts:
                return {
                    'ticker': ticker,
                    'status': 'no_data',
                    'total_posts': 0
                }
            
            # Save individual posts if requested
            if save_posts_detail:
                self.save_posts(posts, ticker)
            
            # Aggregate daily sentiment
            daily_sentiment = self.aggregate_daily_sentiment(posts, ticker)
            
            # Save aggregated data
            self.save_daily_sentiment(daily_sentiment, ticker)
            
            return {
                'ticker': ticker,
                'status': 'success',
                'total_posts': len(posts),
                'date_range': {
                    'earliest': daily_sentiment['date'].min().strftime('%Y-%m-%d'),
                    'latest': daily_sentiment['date'].max().strftime('%Y-%m-%d')
                },
                'avg_daily_mentions': daily_sentiment['mention_count'].mean(),
                'avg_sentiment': daily_sentiment['avg_sentiment'].mean()
            }
            
        except Exception as e:
            logger.error(f"Failed to collect Reddit data for {ticker}: {str(e)}")
            return {
                'ticker': ticker,
                'status': 'failed',
                'error': str(e)
            }
    
    def collect_for_multiple_tickers(self, tickers, save_posts_detail=True):
        """
        Collect Reddit sentiment for multiple tickers
        
        Args:
            tickers: List of ticker symbols
            save_posts_detail: Whether to save individual posts
        
        Returns:
            List of results for each ticker
        """
        # Load all CSV files once
        logger.info("Loading CSV dumps...")
        all_posts_df = self.load_csv_files()
        
        results = []
        
        for i, ticker in enumerate(tickers, 1):
            logger.info(f"Processing {ticker} ({i}/{len(tickers)})")
            
            result = self.collect_for_ticker(
                ticker,
                all_posts_df,
                save_posts_detail=save_posts_detail
            )
            results.append(result)
            
            # Progress update
            if i % 5 == 0:
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
    collector = RedditSentimentCollector(
        csv_dir='data/reddit_dump/reddit/submissions',  # Directory with your CSV files
        output_dir='data/processed/reddit-sentiment'    # Directory to save results
    )
    
    # Test with small batch
    tickers = ['AAPL', 'TSLA', 'GME', 'NVDA', 'AMD']
    
    print(f"\nCollecting Reddit sentiment for {len(tickers)} stocks")
    print(f"From CSV dumps in: {collector.csv_dir}\n")
    
    results = collector.collect_for_multiple_tickers(
        tickers,
        save_posts_detail=True
    )
    
    # Print summary
    print("\n" + "="*60)
    print("RESULTS SUMMARY")
    print("="*60)
    for result in results:
        print(f"\n{result['ticker']}: {result['status']}")
        if result['status'] == 'success':
            print(f"  Total posts: {result['total_posts']}")
            print(f"  Date range: {result['date_range']['earliest']} to {result['date_range']['latest']}")
            print(f"  Avg daily mentions: {result['avg_daily_mentions']:.1f}")
            print(f"  Avg sentiment: {result['avg_sentiment']:.2f}")


if __name__ == '__main__':
    main()