#!/usr/bin/env python3
"""
Quick Summary Statistics CLI
Fast overview of your data availability and coverage

Usage:
    python summary_cli.py --view overview
    python summary_cli.py --view tickers
    python summary_cli.py --view sentiment
    python summary_cli.py --view coverage --ticker AAPL
"""

import argparse
import os
import psycopg2
import pandas as pd
from tabulate import tabulate
import sys
from dotenv import load_dotenv


load_dotenv()

class QuickSummary:
    def __init__(self, conn_string):
        self.conn_string = conn_string
    
    def get_connection(self):
        return psycopg2.connect(self.conn_string)
    
    def show_overview(self):
        """Show high-level overview"""
        print("\n" + "="*70)
        print("DATABASE OVERVIEW")
        print("="*70)
        
        with self.get_connection() as conn:
            df = pd.read_sql("SELECT * FROM summary_overall_stats", conn)
        
        print(f"\n{tabulate(df, headers='keys', tablefmt='grid', showindex=False)}")
    
    def show_top_tickers(self, n=15):
        """Show top tickers by data coverage"""
        print("\n" + "="*70)
        print(f"TOP {n} TICKERS BY DATA COVERAGE")
        print("="*70)
        
        query = f"""
        SELECT 
            symbol,
            company_name,
            price_days,
            reddit_posts,
            news_articles,
            sec_filings,
            overall_data_quality
        FROM summary_ticker_availability
        ORDER BY price_days DESC, reddit_posts DESC
        LIMIT {n}
        """
        
        with self.get_connection() as conn:
            df = pd.read_sql(query, conn)
        
        print(f"\n{tabulate(df, headers='keys', tablefmt='grid', showindex=False)}")
    
    def show_sentiment_summary(self):
        """Show sentiment statistics"""
        print("\n" + "="*70)
        print("SENTIMENT ANALYSIS SUMMARY")
        print("="*70)
        
        with self.get_connection() as conn:
            df = pd.read_sql("SELECT * FROM summary_sentiment_stats", conn)
        
        # Format for display
        display_cols = [
            'source', 'total_records', 'mean_score', 'median_score',
            'std_dev', 'positive_count', 'negative_count', 'neutral_count'
        ]
        
        print(f"\n{tabulate(df[display_cols], headers='keys', tablefmt='grid', showindex=False)}")
    
    def show_ticker_detail(self, symbol):
        """Show detailed stats for a specific ticker"""
        print("\n" + "="*70)
        print(f"DETAILED STATISTICS FOR {symbol}")
        print("="*70)
        
        query = f"""
        SELECT * FROM summary_ticker_availability
        WHERE symbol = '{symbol}'
        """
        
        with self.get_connection() as conn:
            df = pd.read_sql(query, conn)
        
        if len(df) == 0:
            print(f"\n✗ Ticker '{symbol}' not found in database")
            return
        
        row = df.iloc[0]
        
        print("\n📊 PRICE DATA:")
        print(f"  Trading Days: {row['price_days']}")
        print(f"  Date Range: {row['price_start_date']} to {row['price_end_date']}")
        print(f"  Coverage: {row['price_coverage']}")
        
        print("\n💬 REDDIT DATA:")
        print(f"  Total Posts: {row['reddit_posts']}")
        print(f"  Date Range: {row['reddit_first_mention']} to {row['reddit_last_mention']}")
        print(f"  Sentiment Count: {row['reddit_sentiment_count']}")
        print(f"  Avg Sentiment: {row['reddit_avg_sentiment']}")
        
        print("\n📰 NEWS DATA:")
        print(f"  Total Articles: {row['news_articles']}")
        print(f"  Date Range: {row['news_first_mention']} to {row['news_last_mention']}")
        print(f"  Sentiment Count: {row['news_sentiment_count']}")
        print(f"  Avg Sentiment: {row['news_avg_sentiment']}")
        
        print("\n📄 SEC DATA:")
        print(f"  Total Filings: {row['sec_filings']}")
        print(f"  10-K Filings: {row['sec_10k_count']}")
        print(f"  10-Q Filings: {row['sec_10q_count']}")
        print(f"  8-K Filings: {row['sec_8k_count']}")
        print(f"  Date Range: {row['sec_first_filing']} to {row['sec_last_filing']}")
        
        print(f"\n🎯 OVERALL QUALITY: {row['overall_data_quality']}")
    
    def show_monthly_density(self, months=12):
        """Show data density by month"""
        print("\n" + "="*70)
        print(f"DATA DENSITY - LAST {months} MONTHS")
        print("="*70)
        
        query = f"""
        SELECT 
            TO_CHAR(month, 'YYYY-MM') as month,
            price_records,
            reddit_posts,
            news_articles,
            sec_filings
        FROM summary_time_series_density
        ORDER BY month DESC
        LIMIT {months}
        """
        
        with self.get_connection() as conn:
            df = pd.read_sql(query, conn)
        
        print(f"\n{tabulate(df, headers='keys', tablefmt='grid', showindex=False)}")
    
    def show_sector_summary(self):
        """Show sector-level statistics"""
        print("\n" + "="*70)
        print("SECTOR ANALYSIS")
        print("="*70)
        
        query = """
        SELECT 
            sector,
            ticker_count,
            total_reddit_mentions,
            total_news_articles,
            total_sec_filings,
            avg_reddit_sentiment,
            avg_news_sentiment
        FROM summary_sector_stats
        ORDER BY ticker_count DESC
        """
        
        with self.get_connection() as conn:
            df = pd.read_sql(query, conn)
        
        if len(df) > 0:
            print(f"\n{tabulate(df, headers='keys', tablefmt='grid', showindex=False)}")
        else:
            print("\n⚠ No sector information available")
    
    def show_data_gaps(self, min_gap_days=7):
        """Show significant data gaps"""
        print("\n" + "="*70)
        print(f"DATA GAPS (>{min_gap_days} days)")
        print("="*70)
        
        query = f"""
        SELECT * FROM summary_data_gaps
        WHERE gap_days > {min_gap_days}
        ORDER BY gap_days DESC
        LIMIT 20
        """
        
        with self.get_connection() as conn:
            df = pd.read_sql(query, conn)
        
        if len(df) > 0:
            print(f"\n{tabulate(df, headers='keys', tablefmt='grid', showindex=False)}")
            print(f"\nTotal gaps found: {len(df)}")
        else:
            print(f"\n✓ No gaps larger than {min_gap_days} days found!")
    
    def show_most_active(self, n=10):
        """Show most active tickers"""
        print("\n" + "="*70)
        print(f"TOP {n} MOST ACTIVE TICKERS")
        print("="*70)
        
        query = f"""
        SELECT 
            symbol,
            reddit_mentions,
            news_mentions,
            total_filings,
            reddit_avg_sentiment,
            news_avg_sentiment,
            activity_score
        FROM summary_ticker_activity
        ORDER BY activity_score DESC
        LIMIT {n}
        """
        
        with self.get_connection() as conn:
            df = pd.read_sql(query, conn)
        
        print(f"\n{tabulate(df, headers='keys', tablefmt='grid', showindex=False)}")
    
    def show_price_stats(self, n=10):
        """Show price statistics for top tickers"""
        print("\n" + "="*70)
        print(f"PRICE STATISTICS - TOP {n} TICKERS")
        print("="*70)
        
        query = f"""
        SELECT 
            symbol,
            trading_days,
            avg_close_price,
            avg_daily_return_pct,
            return_volatility_pct,
            total_return_pct
        FROM summary_price_stats
        ORDER BY trading_days DESC
        LIMIT {n}
        """
        
        with self.get_connection() as conn:
            df = pd.read_sql(query, conn)
        
        print(f"\n{tabulate(df, headers='keys', tablefmt='grid', showindex=False)}")
    
    def show_recent_activity(self, days=7):
        """Show recent daily activity"""
        print("\n" + "="*70)
        print(f"RECENT ACTIVITY - LAST {days} DAYS")
        print("="*70)
        
        query = f"""
        SELECT * FROM summary_recent_activity
        ORDER BY date DESC
        LIMIT {days}
        """
        
        with self.get_connection() as conn:
            df = pd.read_sql(query, conn)
        
        print(f"\n{tabulate(df, headers='keys', tablefmt='grid', showindex=False)}")


def main():
    parser = argparse.ArgumentParser(
        description='Quick Summary Statistics Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    DB_CONFIG = {
        'dbname': os.getenv('DB_NAME'),
        'user': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASSWORD'),
        'host': os.getenv('DB_HOST'),
        'port': os.getenv('DB_PORT')
    }
    
    parser.add_argument(
        '--view',
        choices=[
            'overview', 'tickers', 'sentiment', 'density', 
            'sectors', 'gaps', 'active', 'prices', 'recent', 'all'
        ],
        default='overview',
        help='Which summary view to display'
    )
    
    parser.add_argument(
        '--ticker',
        help='Show detailed stats for specific ticker'
    )
    
    parser.add_argument(
        '--top',
        type=int,
        default=15,
        help='Number of top items to show'
    )
    
    parser.add_argument(
        '--db',
        default=f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}",
        help='Database connection string'
    )
    
    args = parser.parse_args()
    
    summary = QuickSummary(args.db)
    
    try:
        print(f"\n{'='*70}")
        print("STOCK EVENT DATABASE - SUMMARY STATISTICS")
        print(f"{'='*70}")
        
        if args.ticker:
            summary.show_ticker_detail(args.ticker.upper())
        elif args.view == 'overview':
            summary.show_overview()
        elif args.view == 'tickers':
            summary.show_top_tickers(args.top)
        elif args.view == 'sentiment':
            summary.show_sentiment_summary()
        elif args.view == 'density':
            summary.show_monthly_density()
        elif args.view == 'sectors':
            summary.show_sector_summary()
        elif args.view == 'gaps':
            summary.show_data_gaps()
        elif args.view == 'active':
            summary.show_most_active(args.top)
        elif args.view == 'prices':
            summary.show_price_stats(args.top)
        elif args.view == 'recent':
            summary.show_recent_activity()
        elif args.view == 'all':
            summary.show_overview()
            summary.show_top_tickers(10)
            summary.show_sentiment_summary()
            summary.show_most_active(10)
            summary.show_recent_activity(7)
        
        print("\n" + "="*70 + "\n")
        
    except psycopg2.Error as e:
        print(f"\n✗ Database error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
