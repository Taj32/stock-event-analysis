#!/usr/bin/env python3
"""
Quick Data Quality Check CLI
Run quick validation checks from command line

Usage:
    python quick_validation.py --check all
    python quick_validation.py --check freshness
    python quick_validation.py --check duplicates
    python quick_validation.py --check coverage
"""

import argparse
import os
from dotenv import load_dotenv
import psycopg2
import pandas as pd
from datetime import datetime
from tabulate import tabulate
import sys

load_dotenv()


class QuickValidator:
    def __init__(self, conn_string):
        self.conn_string = conn_string
    
    def get_connection(self):
        return psycopg2.connect(self.conn_string)
    
    def check_sql_rules(self):
        """Run SQL validation rules"""
        print("\n" + "="*70)
        print("SQL VALIDATION RULES")
        print("="*70)
        
        with self.get_connection() as conn:
            df = pd.read_sql("SELECT * FROM run_all_quality_checks()", conn)
        
        # Print summary
        print(f"\nTotal: {len(df)} | "
              f"✓ Pass: {len(df[df['status'] == 'pass'])} | "
              f"✗ Fail: {len(df[df['status'] == 'fail'])} | "
              f"⚠ Warn: {len(df[df['status'] == 'warning'])}")
        
        # Show only failures and warnings
        issues = df[df['status'].isin(['fail', 'warning'])]
        
        if len(issues) > 0:
            print("\nISSUES FOUND:")
            print(tabulate(
                issues[['rule_name', 'severity', 'records_failed', 'status', 'description']],
                headers='keys',
                tablefmt='grid',
                showindex=False
            ))
        else:
            print("\n✓ All validation checks passed!")
        
        return df
    
    def check_freshness(self):
        """Check data freshness"""
        print("\n" + "="*70)
        print("DATA FRESHNESS CHECK")
        print("="*70)
        
        queries = {
            'Reddit Posts': "SELECT MAX(created_utc) FROM reddit_posts",
            'News Articles': "SELECT MAX(published_at) FROM news_articles",
            'SEC Filings': "SELECT MAX(filing_date) FROM sec_filings",
            'Stock Prices': "SELECT MAX(date) FROM stock_prices"
        }
        
        results = []
        with self.get_connection() as conn:
            for source, query in queries.items():
                df = pd.read_sql(query, conn)
                latest = df.iloc[0, 0]
                
                if latest:
                    if isinstance(latest, pd.Timestamp):
                        age_hours = (pd.Timestamp.now() - latest).total_seconds() / 3600
                    else:
                        age_hours = (pd.Timestamp.now() - pd.Timestamp(latest)).total_seconds() / 3600
                    
                    status = "✓ Fresh" if age_hours < 48 else "⚠ Stale"
                    age_str = f"{age_hours:.1f}h"
                else:
                    status = "✗ No Data"
                    age_str = "N/A"
                
                results.append({
                    'Source': source,
                    'Latest': str(latest) if latest else 'None',
                    'Age': age_str,
                    'Status': status
                })
        
        print("\n" + tabulate(results, headers='keys', tablefmt='grid'))
    
    def check_duplicates(self):
        """Check for duplicate records"""
        print("\n" + "="*70)
        print("DUPLICATE RECORDS CHECK")
        print("="*70)
        
        queries = {
            'Reddit Posts (by post_id)': """
                SELECT COUNT(*) as duplicates
                FROM (
                    SELECT post_id FROM reddit_posts 
                    GROUP BY post_id HAVING COUNT(*) > 1
                ) dupes
            """,
            'News Articles (by URL)': """
                SELECT COUNT(*) as duplicates
                FROM (
                    SELECT url FROM news_articles 
                    GROUP BY url HAVING COUNT(*) > 1
                ) dupes
            """,
            'SEC Filings (by accession)': """
                SELECT COUNT(*) as duplicates
                FROM (
                    SELECT accession_number FROM sec_filings 
                    GROUP BY accession_number HAVING COUNT(*) > 1
                ) dupes
            """,
            'Stock Prices (by ticker+date)': """
                SELECT COUNT(*) as duplicates
                FROM (
                    SELECT ticker_id, date FROM stock_prices 
                    GROUP BY ticker_id, date HAVING COUNT(*) > 1
                ) dupes
            """
        }
        
        results = []
        with self.get_connection() as conn:
            for check_name, query in queries.items():
                df = pd.read_sql(query, conn)
                dup_count = df['duplicates'].iloc[0]
                status = "✓ Clean" if dup_count == 0 else f"⚠ {dup_count} duplicates"
                
                results.append({
                    'Check': check_name,
                    'Duplicates': dup_count,
                    'Status': status
                })
        
        print("\n" + tabulate(results, headers='keys', tablefmt='grid'))
    
    def check_coverage(self, top_n=10):
        """Check ticker data coverage"""
        print("\n" + "="*70)
        print(f"TICKER COVERAGE (Top {top_n} by price data)")
        print("="*70)
        
        query = f"""
        SELECT 
            t.symbol,
            COUNT(DISTINCT sp.date) as price_days,
            COUNT(DISTINCT rpt.reddit_post_id) as reddit_posts,
            COUNT(DISTINCT nat.news_article_id) as news_articles,
            COUNT(DISTINCT sf.filing_id) as sec_filings
        FROM tickers t
        LEFT JOIN stock_prices sp ON t.ticker_id = sp.ticker_id
        LEFT JOIN reddit_post_tickers rpt ON t.ticker_id = rpt.ticker_id
        LEFT JOIN news_article_tickers nat ON t.ticker_id = nat.ticker_id
        LEFT JOIN sec_filings sf ON t.ticker_id = sf.ticker_id
        GROUP BY t.ticker_id, t.symbol
        ORDER BY price_days DESC
        LIMIT {top_n};
        """
        
        with self.get_connection() as conn:
            df = pd.read_sql(query, conn)
        
        print("\n" + tabulate(df, headers='keys', tablefmt='grid', showindex=False))
        
        # Summary stats
        total_query = "SELECT COUNT(*) as total FROM tickers"
        with self.get_connection() as conn:
            total = pd.read_sql(total_query, conn)['total'].iloc[0]
        
        print(f"\nTotal tickers in database: {total}")
    
    def check_record_counts(self):
        """Show record counts for all tables"""
        print("\n" + "="*70)
        print("RECORD COUNTS")
        print("="*70)
        
        tables = [
            'tickers',
            'stock_prices',
            'reddit_posts',
            'reddit_post_tickers',
            'reddit_post_sentiment',
            'news_articles',
            'news_article_tickers',
            'news_article_sentiment',
            'sec_filings',
            'sec_filing_sentiment'
        ]
        
        results = []
        with self.get_connection() as conn:
            for table in tables:
                query = f"SELECT COUNT(*) as count FROM {table}"
                df = pd.read_sql(query, conn)
                count = df['count'].iloc[0]
                results.append({
                    'Table': table,
                    'Records': f"{count:,}"
                })
        
        print("\n" + tabulate(results, headers='keys', tablefmt='grid'))
    
    def check_date_ranges(self):
        """Show date ranges for time-based tables"""
        print("\n" + "="*70)
        print("DATE RANGES")
        print("="*70)
        
        queries = {
            'Stock Prices': "SELECT MIN(date) as min_date, MAX(date) as max_date FROM stock_prices",
            'Reddit Posts': "SELECT MIN(created_utc) as min_date, MAX(created_utc) as max_date FROM reddit_posts",
            'News Articles': "SELECT MIN(published_at) as min_date, MAX(published_at) as max_date FROM news_articles",
            'SEC Filings': "SELECT MIN(filing_date) as min_date, MAX(filing_date) as max_date FROM sec_filings"
        }
        
        results = []
        with self.get_connection() as conn:
            for source, query in queries.items():
                df = pd.read_sql(query, conn)
                min_date = df['min_date'].iloc[0]
                max_date = df['max_date'].iloc[0]
                
                if min_date and max_date:
                    span_days = (pd.Timestamp(max_date) - pd.Timestamp(min_date)).days
                    results.append({
                        'Source': source,
                        'Earliest': str(min_date)[:10],
                        'Latest': str(max_date)[:10],
                        'Span (days)': span_days
                    })
                else:
                    results.append({
                        'Source': source,
                        'Earliest': 'N/A',
                        'Latest': 'N/A',
                        'Span (days)': 'N/A'
                    })
        
        print("\n" + tabulate(results, headers='keys', tablefmt='grid'))


def main():
    
    DB_CONFIG = {
        'dbname': os.getenv('DB_NAME'),
        'user': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASSWORD'),
        'host': os.getenv('DB_HOST'),
        'port': os.getenv('DB_PORT')
    }
    
    parser = argparse.ArgumentParser(
        description='Quick Data Quality Validation Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--check',
        choices=['all', 'rules', 'freshness', 'duplicates', 'coverage', 'counts', 'dates'],
        default='all',
        help='Type of validation check to run'
    )
    
    parser.add_argument(
        '--db',
        default=f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}",
        help='Database connection string'
    )
    
    parser.add_argument(
        '--top',
        type=int,
        default=10,
        help='Number of top items to show in coverage check'
    )
    
    args = parser.parse_args()
    
    # Initialize validator
    validator = QuickValidator(args.db)
    
    try:
        print(f"\n{'='*70}")
        print(f"STOCK EVENT DATA QUALITY CHECK - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*70}")
        
        if args.check in ['all', 'counts']:
            validator.check_record_counts()
        
        if args.check in ['all', 'dates']:
            validator.check_date_ranges()
        
        if args.check in ['all', 'freshness']:
            validator.check_freshness()
        
        if args.check in ['all', 'duplicates']:
            validator.check_duplicates()
        
        if args.check in ['all', 'coverage']:
            validator.check_coverage(args.top)
        
        if args.check in ['all', 'rules']:
            validator.check_sql_rules()
        
        print("\n" + "="*70)
        print("✓ Validation complete!")
        print("="*70 + "\n")
        
    except psycopg2.Error as e:
        print(f"\n✗ Database error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
