#!/usr/bin/env python3
"""
Date Alignment Validation Script
Tests that events are properly aligned to trading days
"""

import os
from dotenv import load_dotenv
import psycopg2
import pandas as pd
from datetime import datetime, timedelta
from tabulate import tabulate
load_dotenv()


class AlignmentValidator:
    def __init__(self, conn_string):
        self.conn_string = conn_string
    
    def get_connection(self):
        return psycopg2.connect(self.conn_string)
    
    def test_alignment_function(self):
        """Test the alignment function with known cases"""
        print("\n" + "="*70)
        print("TESTING ALIGNMENT FUNCTION")
        print("="*70)
        
        test_cases = [
            # (timestamp, expected_behavior, description)
            ('2024-01-24 14:00:00-05', 'same day', 'Wednesday 2 PM (market hours)'),
            ('2024-01-24 18:30:00-05', 'next day', 'Wednesday 6:30 PM (after close)'),
            ('2024-01-24 08:00:00-05', 'same day', 'Wednesday 8 AM (before open)'),
            ('2024-01-20 15:00:00-05', 'next Monday', 'Saturday 3 PM (weekend)'),
            ('2024-01-21 10:00:00-05', 'next Monday', 'Sunday 10 AM (weekend)'),
            ('2024-12-25 12:00:00-05', 'next trading', 'Christmas Day (holiday)'),
        ]
        
        results = []
        with self.get_connection() as conn:
            for ts, expected, desc in test_cases:
                query = f"""
                SELECT 
                    '{ts}'::TIMESTAMP WITH TIME ZONE as input_timestamp,
                    trading_date,
                    is_market_hours,
                    alignment_rule
                FROM align_to_trading_day('{ts}'::TIMESTAMP WITH TIME ZONE)
                """
                df = pd.read_sql(query, conn)
                
                if len(df) > 0:
                    results.append({
                        'Test Case': desc,
                        'Input': str(ts)[:16],
                        'Aligned To': str(df['trading_date'].iloc[0]),
                        'Rule': df['alignment_rule'].iloc[0],
                        'Market Hours': '✓' if df['is_market_hours'].iloc[0] else '✗'
                    })
        
        print(f"\n{tabulate(results, headers='keys', tablefmt='grid')}")
    
    def check_alignment_coverage(self):
        """Check that all events have been aligned"""
        print("\n" + "="*70)
        print("ALIGNMENT COVERAGE CHECK")
        print("="*70)
        
        queries = {
            'Reddit Posts': """
                SELECT 
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE trading_date IS NOT NULL) as aligned,
                    COUNT(*) FILTER (WHERE trading_date IS NULL) as unaligned
                FROM reddit_posts
            """,
            'News Articles': """
                SELECT 
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE trading_date IS NOT NULL) as aligned,
                    COUNT(*) FILTER (WHERE trading_date IS NULL) as unaligned
                FROM news_articles
            """,
            'SEC Filings': """
                SELECT 
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE trading_date IS NOT NULL) as aligned,
                    COUNT(*) FILTER (WHERE trading_date IS NULL) as unaligned
                FROM sec_filings
            """
        }
        
        results = []
        with self.get_connection() as conn:
            for source, query in queries.items():
                df = pd.read_sql(query, conn)
                row = df.iloc[0]
                
                status = '✓ Complete' if row['unaligned'] == 0 else f"⚠ {row['unaligned']} unaligned"
                pct = (row['aligned'] / row['total'] * 100) if row['total'] > 0 else 0
                
                results.append({
                    'Source': source,
                    'Total': row['total'],
                    'Aligned': row['aligned'],
                    'Unaligned': row['unaligned'],
                    'Coverage %': f"{pct:.1f}%",
                    'Status': status
                })
        
        print(f"\n{tabulate(results, headers='keys', tablefmt='grid')}")
    
    def check_alignment_distribution(self):
        """Show distribution of alignment rules"""
        print("\n" + "="*70)
        print("ALIGNMENT RULE DISTRIBUTION")
        print("="*70)
        
        query = "SELECT * FROM alignment_statistics"
        
        with self.get_connection() as conn:
            df = pd.read_sql(query, conn)
        
        print(f"\n{tabulate(df, headers='keys', tablefmt='grid', showindex=False)}")
    
    def check_weekend_alignment(self):
        """Verify weekend events are aligned to Monday"""
        print("\n" + "="*70)
        print("WEEKEND ALIGNMENT VERIFICATION")
        print("="*70)
        
        query = """
        SELECT 
            source,
            COUNT(*) as weekend_events,
            COUNT(*) FILTER (WHERE EXTRACT(DOW FROM trading_date) = 1) as aligned_to_monday,
            COUNT(*) FILTER (WHERE EXTRACT(DOW FROM trading_date) != 1) as aligned_to_other
        FROM unified_events_aligned
        WHERE EXTRACT(DOW FROM original_timestamp::DATE) IN (0, 6)  -- Weekend
        GROUP BY source
        """
        
        with self.get_connection() as conn:
            df = pd.read_sql(query, conn)
        
        if len(df) > 0:
            print(f"\n{tabulate(df, headers='keys', tablefmt='grid', showindex=False)}")
            print("\nNote: Weekend events should typically align to Monday (DOW=1)")
        else:
            print("\n✓ No weekend events found (or no events at all)")
    
    def check_joinability_with_prices(self):
        """Test that aligned events can join with stock prices"""
        print("\n" + "="*70)
        print("PRICE DATA JOINABILITY TEST")
        print("="*70)
        
        queries = {
            'Reddit Posts': """
                SELECT 
                    COUNT(DISTINCT rp.reddit_post_id) as total_posts,
                    COUNT(DISTINCT CASE WHEN sp.price_id IS NOT NULL THEN rp.reddit_post_id END) as joinable_posts
                FROM reddit_posts rp
                JOIN reddit_post_tickers rpt ON rp.reddit_post_id = rpt.reddit_post_id
                LEFT JOIN stock_prices sp ON rp.trading_date = sp.date 
                    AND rpt.ticker_id = sp.ticker_id
                WHERE rp.trading_date IS NOT NULL
            """,
            'News Articles': """
                SELECT 
                    COUNT(DISTINCT na.news_article_id) as total_articles,
                    COUNT(DISTINCT CASE WHEN sp.price_id IS NOT NULL THEN na.news_article_id END) as joinable_articles
                FROM news_articles na
                JOIN news_article_tickers nat ON na.news_article_id = nat.news_article_id
                LEFT JOIN stock_prices sp ON na.trading_date = sp.date 
                    AND nat.ticker_id = sp.ticker_id
                WHERE na.trading_date IS NOT NULL
            """,
            'SEC Filings': """
                SELECT 
                    COUNT(DISTINCT sf.filing_id) as total_filings,
                    COUNT(DISTINCT CASE WHEN sp.price_id IS NOT NULL THEN sf.filing_id END) as joinable_filings
                FROM sec_filings sf
                LEFT JOIN stock_prices sp ON sf.trading_date = sp.date 
                    AND sf.ticker_id = sp.ticker_id
                WHERE sf.trading_date IS NOT NULL
            """
        }
        
        results = []
        with self.get_connection() as conn:
            for source, query in queries.items():
                df = pd.read_sql(query, conn)
                if len(df) > 0:
                    row = df.iloc[0]
                    total = row.iloc[0]
                    joinable = row.iloc[1]
                    
                    if total > 0:
                        pct = (joinable / total * 100)
                        status = '✓ Good' if pct > 80 else '⚠ Low' if pct > 50 else '✗ Poor'
                    else:
                        pct = 0
                        status = 'No data'
                    
                    results.append({
                        'Source': source,
                        'Total Events': total,
                        'Joinable': joinable,
                        'Not Joinable': total - joinable,
                        'Join Rate %': f"{pct:.1f}%",
                        'Status': status
                    })
        
        print(f"\n{tabulate(results, headers='keys', tablefmt='grid')}")
        print("\nNote: Events should join with price data. Low rates may indicate:")
        print("  • Missing price data for those tickers")
        print("  • Events outside your price data date range")
        print("  • Ticker mapping issues")
    
    def show_sample_alignments(self, n=10):
        """Show sample aligned events"""
        print("\n" + "="*70)
        print(f"SAMPLE ALIGNED EVENTS (Random {n})")
        print("="*70)
        
        query = f"""
        SELECT 
            ticker,
            source,
            event_type,
            original_timestamp,
            trading_date,
            alignment_rule,
            direction
        FROM unified_events_aligned
        ORDER BY RANDOM()
        LIMIT {n}
        """
        
        with self.get_connection() as conn:
            df = pd.read_sql(query, conn)
        
        if len(df) > 0:
            # Format timestamps for display
            df['original_timestamp'] = pd.to_datetime(df['original_timestamp']).dt.strftime('%Y-%m-%d %H:%M')
            print(f"\n{tabulate(df, headers='keys', tablefmt='grid', showindex=False)}")
        else:
            print("\n⚠ No aligned events found")
    
    def check_trading_calendar(self):
        """Verify trading calendar is populated"""
        print("\n" + "="*70)
        print("TRADING CALENDAR VERIFICATION")
        print("="*70)
        
        query = """
        SELECT 
            MIN(calendar_date) as earliest_date,
            MAX(calendar_date) as latest_date,
            COUNT(*) as total_days,
            COUNT(*) FILTER (WHERE is_trading_day = TRUE) as trading_days,
            COUNT(*) FILTER (WHERE is_trading_day = FALSE) as non_trading_days,
            COUNT(*) FILTER (WHERE holiday_name IS NOT NULL) as holidays
        FROM trading_calendar
        """
        
        with self.get_connection() as conn:
            df = pd.read_sql(query, conn)
        
        if len(df) > 0:
            row = df.iloc[0]
            print(f"\nDate Range: {row['earliest_date']} to {row['latest_date']}")
            print(f"Total Days: {row['total_days']}")
            print(f"Trading Days: {row['trading_days']} ({row['trading_days']/row['total_days']*100:.1f}%)")
            print(f"Non-Trading: {row['non_trading_days']} ({row['non_trading_days']/row['total_days']*100:.1f}%)")
            print(f"Holidays: {row['holidays']}")
            
            # Show some holidays
            holidays_query = """
            SELECT calendar_date, holiday_name
            FROM trading_calendar
            WHERE holiday_name IS NOT NULL
            ORDER BY calendar_date DESC
            LIMIT 10
            """
            holidays_df = pd.read_sql(holidays_query, conn)
            print("\nRecent Holidays:")
            print(tabulate(holidays_df, headers='keys', tablefmt='grid', showindex=False))
        else:
            print("\n✗ Trading calendar is empty!")
    
    def run_all_validations(self):
        """Run complete validation suite"""
        print("\n" + "="*70)
        print("DATE ALIGNMENT VALIDATION SUITE")
        print(f"Run Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*70)
        
        try:
            self.check_trading_calendar()
            self.test_alignment_function()
            self.check_alignment_coverage()
            self.check_alignment_distribution()
            self.check_weekend_alignment()
            self.check_joinability_with_prices()
            self.show_sample_alignments()
            
            print("\n" + "="*70)
            print("✓ VALIDATION COMPLETE")
            print("="*70)
            
        except Exception as e:
            print(f"\n✗ Validation error: {e}")
            raise


def main():
    import argparse
    
    DB_CONFIG = {
        'dbname': os.getenv('DB_NAME'),
        'user': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASSWORD'),
        'host': os.getenv('DB_HOST'),
        'port': os.getenv('DB_PORT')
    }
    
    parser = argparse.ArgumentParser(description='Validate Date Alignment System')
    parser.add_argument(
        '--db',
        default=f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}",
        help='Database connection string'
    )
    
    args = parser.parse_args()
    
    validator = AlignmentValidator(args.db)
    validator.run_all_validations()


if __name__ == "__main__":
    main()
