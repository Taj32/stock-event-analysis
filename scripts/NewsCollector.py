"""
News collector using Finnhub API
"""
import requests
import os
import pandas as pd
import json
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
import sys
sys.path.append(str(Path(__file__).parent.parent))

from utils.rate_limiter import finnhub_limiter
from utils.error_handler import safe_api_call, create_logger, handle_response
from utils.date_utils import format_date, chunk_date_range

load_dotenv()
logger = create_logger(__name__)


class NewsCollector:
    """Collector for financial news using Finnhub API"""
    
    def __init__(self, api_key=None, output_dir='data/raw/news'):
        self.api_key = api_key or os.getenv('FINNHUB_API_KEY')
        if not self.api_key:
            raise ValueError(
                "Finnhub API key not found. Set FINNHUB_API_KEY in .env\n"
                "Get free key at: https://finnhub.io/register"
            )
        
        self.base_url = 'https://finnhub.io/api/v1'
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("Initialized Finnhub news collector")
    
    @finnhub_limiter
    @safe_api_call
    def fetch_company_news(self, ticker, start_date, end_date):
        """
        Fetch company-specific news from Finnhub
        
        Args:
            ticker: Stock ticker symbol
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        
        Returns:
            List of news articles
        """
        logger.info(f"Fetching news for {ticker} from {start_date} to {end_date}")
        
        url = f"{self.base_url}/company-news"
        params = {
            'symbol': ticker,
            'from': start_date,
            'to': end_date,
            'token': self.api_key
        }
        
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            articles = response.json()
            logger.info(f"Retrieved {len(articles)} articles for {ticker}")
            return articles
        else:
            logger.error(f"Failed to fetch news for {ticker}: {response.status_code}")
            raise Exception(f"Finnhub API error: {response.status_code}")
    
    @finnhub_limiter
    @safe_api_call
    def fetch_news_sentiment(self, ticker):
        """
        Fetch news sentiment for a ticker
        Note: This is an aggregate sentiment, not per-article
        
        Args:
            ticker: Stock ticker symbol
        
        Returns:
            Dictionary with sentiment data
        """
        logger.info(f"Fetching news sentiment for {ticker}")
        
        url = f"{self.base_url}/news-sentiment"
        params = {
            'symbol': ticker,
            'token': self.api_key
        }
        
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.warning(f"Could not fetch sentiment for {ticker}: {response.status_code}")
            return None
    
    def simple_headline_sentiment(self, headline):
        """
        Simple sentiment analysis based on headline keywords
        
        Args:
            headline: Article headline
        
        Returns:
            Sentiment score between -1 (negative) and 1 (positive)
        """
        if not headline:
            return 0.0
        
        headline_lower = headline.lower()
        
        # Positive keywords
        positive_words = [
            'surge', 'soar', 'jump', 'gain', 'rise', 'up', 'high', 'beat',
            'exceed', 'strong', 'growth', 'profit', 'success', 'win',
            'breakthrough', 'record', 'rally', 'boost', 'positive'
        ]
        
        # Negative keywords
        negative_words = [
            'fall', 'drop', 'plunge', 'decline', 'down', 'low', 'miss',
            'weak', 'loss', 'fail', 'struggle', 'concern', 'warning',
            'risk', 'problem', 'issue', 'negative', 'crash', 'tumble'
        ]
        
        # Count occurrences
        positive_count = sum(1 for word in positive_words if word in headline_lower)
        negative_count = sum(1 for word in negative_words if word in headline_lower)
        
        # Calculate sentiment
        if positive_count + negative_count == 0:
            return 0.0
        
        sentiment = (positive_count - negative_count) / (positive_count + negative_count)
        return sentiment
    
    def parse_news_articles(self, articles, ticker):
        """
        Parse news articles into structured format
        
        Args:
            articles: List of article dictionaries from Finnhub
            ticker: Stock ticker
        
        Returns:
            DataFrame with parsed articles
        """
        if not articles:
            logger.warning(f"No articles to parse for {ticker}")
            return pd.DataFrame()
        
        # Convert to DataFrame
        df = pd.DataFrame(articles)
        
        # Add ticker
        df['ticker'] = ticker
        
        # Convert timestamp to datetime
        if 'datetime' in df.columns:
            df['published_date'] = pd.to_datetime(df['datetime'], unit='s')
        
        # Calculate sentiment from headlines if not provided
        if 'headline' in df.columns:
            df['headline_sentiment'] = df['headline'].apply(self.simple_headline_sentiment)
        
        # Select relevant columns
        columns_to_keep = [
            'ticker', 'published_date', 'headline', 'summary',
            'source', 'url', 'headline_sentiment'
        ]
        
        # Only keep columns that exist
        columns_to_keep = [col for col in columns_to_keep if col in df.columns]
        df = df[columns_to_keep]
        
        # Sort by date (most recent first)
        if 'published_date' in df.columns:
            df = df.sort_values('published_date', ascending=False)
        
        return df
    
    def aggregate_daily_news(self, df):
        """
        Aggregate news articles into daily metrics
        
        Args:
            df: DataFrame with individual articles
        
        Returns:
            DataFrame with daily aggregated metrics
        """
        if df.empty:
            return pd.DataFrame()
        
        # Extract date
        df['date'] = df['published_date'].dt.date
        
        # Group by date
        daily = df.groupby('date').agg({
            'headline': 'count',
            'headline_sentiment': ['mean', 'std'],
            'source': lambda x: list(x.unique())
        }).reset_index()
        
        # Flatten column names
        daily.columns = ['date', 'article_count', 'avg_sentiment', 'sentiment_std', 'sources']
        
        # Calculate positive/negative/neutral counts
        positive_counts = df[df['headline_sentiment'] > 0.1].groupby('date').size()
        negative_counts = df[df['headline_sentiment'] < -0.1].groupby('date').size()
        neutral_counts = df[(df['headline_sentiment'] >= -0.1) & (df['headline_sentiment'] <= 0.1)].groupby('date').size()
        
        daily['positive_count'] = daily['date'].map(positive_counts).fillna(0).astype(int)
        daily['negative_count'] = daily['date'].map(negative_counts).fillna(0).astype(int)
        daily['neutral_count'] = daily['date'].map(neutral_counts).fillna(0).astype(int)
        
        # Get top headline for each day
        top_headlines = df.sort_values('published_date', ascending=False).groupby('date')['headline'].first()
        daily['top_headline'] = daily['date'].map(top_headlines)
        
        # Add ticker
        daily['ticker'] = df['ticker'].iloc[0]
        
        return daily
    
    def save_articles(self, df, ticker):
        """Save individual articles to CSV"""
        output_file = self.output_dir / f"{ticker}_articles.csv"
        df.to_csv(output_file, index=False)
        logger.info(f"Saved {len(df)} articles to {output_file}")
    
    def save_daily_news(self, df, ticker):
        """Save daily aggregated news to CSV"""
        output_file = self.output_dir / f"{ticker}_daily_news.csv"
        
        # Convert sources list to JSON string for CSV
        if 'sources' in df.columns:
            df['sources'] = df['sources'].apply(json.dumps)
        
        df.to_csv(output_file, index=False)
        logger.info(f"Saved daily news metrics to {output_file}")
    
    def save_raw_response(self, articles, ticker, start_date, end_date):
        """Save raw API response to JSON"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = self.output_dir / f"{ticker}_news_raw_{timestamp}.json"
        
        with open(output_file, 'w') as f:
            json.dump(articles, f, indent=2)
        
        logger.info(f"Saved raw news data to {output_file}")
    
    def collect_for_ticker(self, ticker, start_date, end_date, save_raw=True):
        """
        Collect news for a single ticker
        
        Args:
            ticker: Stock ticker
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            save_raw: Whether to save raw API response
        
        Returns:
            Dictionary with status and data
        """
        try:
            # For long date ranges, chunk them (Finnhub might have limits)
            date_chunks = chunk_date_range(start_date, end_date, chunk_size_days=90)
            
            all_articles = []
            
            for chunk_start, chunk_end in date_chunks:
                articles = self.fetch_company_news(
                    ticker,
                    chunk_start.strftime('%Y-%m-%d'),
                    chunk_end.strftime('%Y-%m-%d')
                )
                all_articles.extend(articles)
            
            if not all_articles:
                return {
                    'ticker': ticker,
                    'status': 'no_data',
                    'articles': 0
                }
            
            # Save raw data if requested
            if save_raw:
                self.save_raw_response(all_articles, ticker, start_date, end_date)
            
            # Parse articles
            df = self.parse_news_articles(all_articles, ticker)
            
            # Save individual articles
            self.save_articles(df, ticker)
            
            # Aggregate daily
            daily_news = self.aggregate_daily_news(df)
            
            # Save daily aggregates
            self.save_daily_news(daily_news, ticker)
            
            return {
                'ticker': ticker,
                'status': 'success',
                'total_articles': len(df),
                'date_range': {
                    'earliest': df['published_date'].min().strftime('%Y-%m-%d'),
                    'latest': df['published_date'].max().strftime('%Y-%m-%d')
                },
                'avg_daily_articles': daily_news['article_count'].mean(),
                'avg_sentiment': daily_news['avg_sentiment'].mean()
            }
            
        except Exception as e:
            logger.error(f"Failed to collect news for {ticker}: {str(e)}")
            return {
                'ticker': ticker,
                'status': 'failed',
                'error': str(e)
            }
    
    def collect_for_multiple_tickers(self, tickers, start_date, end_date, save_raw=True):
        """
        Collect news for multiple tickers
        
        Args:
            tickers: List of ticker symbols
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            save_raw: Whether to save raw responses
        
        Returns:
            List of results for each ticker
        """
        results = []
        
        for i, ticker in enumerate(tickers, 1):
            logger.info(f"Processing {ticker} ({i}/{len(tickers)})")
            
            result = self.collect_for_ticker(
                ticker,
                start_date,
                end_date,
                save_raw=save_raw
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
    collector = NewsCollector()
    
    # Test with small batch
    tickers = ['AAPL', 'MSFT', 'GOOGL']
    start_date = '2024-10-01'
    end_date = '2024-11-01'
    
    print(f"\nCollecting news for {len(tickers)} stocks")
    print(f"Date range: {start_date} to {end_date}")
    print("Using Finnhub API (60 calls/min, free tier)\n")
    
    results = collector.collect_for_multiple_tickers(
        tickers,
        start_date,
        end_date
    )
    
    # Print summary
    for result in results:
        print(f"\n{result['ticker']}: {result['status']}")
        if result['status'] == 'success':
            print(f"  Total articles: {result['total_articles']}")
            print(f"  Date range: {result['date_range']}")
            print(f"  Avg daily articles: {result['avg_daily_articles']:.1f}")
            print(f"  Avg sentiment: {result['avg_sentiment']:.2f}")


if __name__ == '__main__':
    main()