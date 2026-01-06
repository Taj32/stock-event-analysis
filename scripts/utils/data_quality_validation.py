"""
Data Quality Validation Scripts
Validates data across all sources and generates detailed reports
"""

import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
import json
from typing import Dict, List, Tuple
import logging
from dotenv import load_dotenv
load_dotenv()


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DataQualityValidator:
    """Main class for running data quality validations"""
    
    def __init__(self, db_connection_string: str):
        """Initialize with database connection"""
        self.conn_string = db_connection_string
        self.results = []
        
    def get_connection(self):
        """Get database connection"""
        return psycopg2.connect(self.conn_string)
    
    def run_all_validations(self) -> pd.DataFrame:
        """Run all SQL-based validation rules"""
        logger.info("Running all SQL validation rules...")
        
        with self.get_connection() as conn:
            query = "SELECT * FROM run_all_quality_checks();"
            df = pd.read_sql(query, conn)
        
        logger.info(f"Completed {len(df)} validation checks")
        logger.info(f"Passed: {len(df[df['status'] == 'pass'])}")
        logger.info(f"Failed: {len(df[df['status'] == 'fail'])}")
        logger.info(f"Warnings: {len(df[df['status'] == 'warning'])}")
        
        return df
    
    def check_data_freshness(self, hours_threshold: int = 24) -> Dict:
        """Check if data is up-to-date"""
        logger.info("Checking data freshness...")
        
        freshness_checks = []
        cutoff_time = datetime.now() - timedelta(hours=hours_threshold)
        
        queries = {
            'reddit_posts': "SELECT MAX(created_utc) as latest FROM reddit_posts",
            'news_articles': "SELECT MAX(published_at) as latest FROM news_articles",
            'sec_filings': "SELECT MAX(filing_date) as latest FROM sec_filings",
            'stock_prices': "SELECT MAX(date) as latest FROM stock_prices"
        }
        
        with self.get_connection() as conn:
            for table, query in queries.items():
                df = pd.read_sql(query, conn)
                latest = df['latest'].iloc[0]
                
                if latest is None:
                    status = 'no_data'
                    hours_old = None
                elif pd.isna(latest):
                    status = 'no_data'
                    hours_old = None
                else:
                    if isinstance(latest, pd.Timestamp):
                        latest_dt = latest
                    else:
                        latest_dt = pd.Timestamp(latest)
                    
                    hours_old = (pd.Timestamp.now() - latest_dt).total_seconds() / 3600
                    status = 'fresh' if hours_old < hours_threshold else 'stale'
                
                freshness_checks.append({
                    'table': table,
                    'latest_record': latest,
                    'hours_old': hours_old,
                    'status': status
                })
                
                logger.info(f"{table}: {status} (latest: {latest})")
        
        return {
            'check_time': datetime.now(),
            'threshold_hours': hours_threshold,
            'results': freshness_checks
        }
    
    def check_data_coverage(self) -> pd.DataFrame:
        """Check ticker coverage across all data sources"""
        logger.info("Checking data coverage across sources...")
        
        query = """
        SELECT 
            t.symbol,
            t.company_name,
            COUNT(DISTINCT sp.date) as price_days,
            COUNT(DISTINCT rpt.reddit_post_id) as reddit_mentions,
            COUNT(DISTINCT nat.news_article_id) as news_mentions,
            COUNT(DISTINCT sf.filing_id) as sec_filings,
            CASE 
                WHEN COUNT(DISTINCT sp.date) = 0 THEN 'no_prices'
                WHEN COUNT(DISTINCT sp.date) < 30 THEN 'limited_prices'
                ELSE 'good_coverage'
            END as coverage_status
        FROM tickers t
        LEFT JOIN stock_prices sp ON t.ticker_id = sp.ticker_id
        LEFT JOIN reddit_post_tickers rpt ON t.ticker_id = rpt.ticker_id
        LEFT JOIN news_article_tickers nat ON t.ticker_id = nat.ticker_id
        LEFT JOIN sec_filings sf ON t.ticker_id = sf.ticker_id
        GROUP BY t.ticker_id, t.symbol, t.company_name
        ORDER BY price_days DESC;
        """
        
        with self.get_connection() as conn:
            df = pd.read_sql(query, conn)
        
        logger.info(f"Coverage check complete for {len(df)} tickers")
        logger.info(f"Tickers with no prices: {len(df[df['coverage_status'] == 'no_prices'])}")
        logger.info(f"Tickers with limited prices: {len(df[df['coverage_status'] == 'limited_prices'])}")
        
        return df
    
    def check_sentiment_distribution(self) -> Dict:
        """Check sentiment score distributions for anomalies"""
        logger.info("Checking sentiment distributions...")
        
        distributions = {}
        
        queries = {
            'reddit': """
                SELECT 
                    sentiment_score,
                    COUNT(*) as count
                FROM reddit_post_sentiment
                GROUP BY sentiment_score
                ORDER BY sentiment_score
            """,
            'news': """
                SELECT 
                    sentiment_score,
                    COUNT(*) as count
                FROM news_article_sentiment
                GROUP BY sentiment_score
                ORDER BY sentiment_score
            """,
            'sec': """
                SELECT 
                    sentiment_score,
                    COUNT(*) as count
                FROM sec_filing_sentiment
                GROUP BY sentiment_score
                ORDER BY sentiment_score
            """
        }
        
        with self.get_connection() as conn:
            for source, query in queries.items():
                df = pd.read_sql(query, conn)
                
                if len(df) > 0:
                    distributions[source] = {
                        'mean': float(df['sentiment_score'].mean()),
                        'median': float(df['sentiment_score'].median()),
                        'std': float(df['sentiment_score'].std()),
                        'min': float(df['sentiment_score'].min()),
                        'max': float(df['sentiment_score'].max()),
                        'total_records': int(df['count'].sum()),
                        'distribution': df.to_dict('records')
                    }
                    
                    logger.info(f"{source} sentiment - Mean: {distributions[source]['mean']:.3f}, "
                              f"Std: {distributions[source]['std']:.3f}")
                else:
                    distributions[source] = {'error': 'no_data'}
        
        return distributions
    
    def check_duplicate_records(self) -> Dict:
        """Check for duplicate records across all tables"""
        logger.info("Checking for duplicate records...")
        
        duplicate_checks = {}
        
        queries = {
            'reddit_posts': """
                SELECT post_id, COUNT(*) as dup_count
                FROM reddit_posts
                GROUP BY post_id
                HAVING COUNT(*) > 1
            """,
            'news_articles': """
                SELECT url, COUNT(*) as dup_count
                FROM news_articles
                GROUP BY url
                HAVING COUNT(*) > 1
            """,
            'sec_filings': """
                SELECT accession_number, COUNT(*) as dup_count
                FROM sec_filings
                GROUP BY accession_number
                HAVING COUNT(*) > 1
            """,
            'stock_prices': """
                SELECT ticker_id, date, COUNT(*) as dup_count
                FROM stock_prices
                GROUP BY ticker_id, date
                HAVING COUNT(*) > 1
            """
        }
        
        with self.get_connection() as conn:
            for table, query in queries.items():
                df = pd.read_sql(query, conn)
                duplicate_checks[table] = {
                    'duplicate_keys': len(df),
                    'total_duplicates': int(df['dup_count'].sum()) if len(df) > 0 else 0
                }
                
                if len(df) > 0:
                    logger.warning(f"{table}: Found {len(df)} duplicate keys")
                else:
                    logger.info(f"{table}: No duplicates found")
        
        return duplicate_checks
    
    def check_time_series_gaps(self, max_gap_days: int = 10) -> pd.DataFrame:
        """Check for large gaps in time series data"""
        logger.info("Checking for time series gaps...")
        
        query = f"""
        WITH price_gaps AS (
            SELECT 
                t.symbol,
                sp.date,
                LAG(sp.date) OVER (PARTITION BY sp.ticker_id ORDER BY sp.date) as prev_date,
                sp.date - LAG(sp.date) OVER (PARTITION BY sp.ticker_id ORDER BY sp.date) as gap_days
            FROM stock_prices sp
            JOIN tickers t ON sp.ticker_id = t.ticker_id
        )
        SELECT 
            symbol,
            prev_date as gap_start,
            date as gap_end,
            gap_days
        FROM price_gaps
        WHERE gap_days > {max_gap_days}
        ORDER BY gap_days DESC, symbol;
        """
        
        with self.get_connection() as conn:
            df = pd.read_sql(query, conn)
        
        if len(df) > 0:
            logger.warning(f"Found {len(df)} gaps larger than {max_gap_days} days")
        else:
            logger.info(f"No gaps larger than {max_gap_days} days found")
        
        return df
    
    def check_extreme_values(self) -> Dict:
        """Check for extreme or suspicious values"""
        logger.info("Checking for extreme values...")
        
        extreme_checks = {}
        
        # Check for extreme price movements
        query_price = """
        WITH daily_returns AS (
            SELECT 
                t.symbol,
                sp.date,
                sp.close,
                LAG(sp.close) OVER (PARTITION BY sp.ticker_id ORDER BY sp.date) as prev_close,
                (sp.close - LAG(sp.close) OVER (PARTITION BY sp.ticker_id ORDER BY sp.date)) / 
                    NULLIF(LAG(sp.close) OVER (PARTITION BY sp.ticker_id ORDER BY sp.date), 0) as pct_change
            FROM stock_prices sp
            JOIN tickers t ON sp.ticker_id = t.ticker_id
        )
        SELECT symbol, date, close, prev_close, pct_change
        FROM daily_returns
        WHERE ABS(pct_change) > 0.20
        ORDER BY ABS(pct_change) DESC
        LIMIT 100;
        """
        
        # Check for extreme sentiment scores
        query_sentiment = """
        SELECT 'reddit' as source, COUNT(*) as extreme_count
        FROM reddit_post_sentiment
        WHERE ABS(sentiment_score) > 0.95
        UNION ALL
        SELECT 'news', COUNT(*)
        FROM news_article_sentiment
        WHERE ABS(sentiment_score) > 0.95
        UNION ALL
        SELECT 'sec', COUNT(*)
        FROM sec_filing_sentiment
        WHERE ABS(sentiment_score) > 0.95;
        """
        
        with self.get_connection() as conn:
            extreme_checks['price_movements'] = pd.read_sql(query_price, conn)
            extreme_checks['extreme_sentiment'] = pd.read_sql(query_sentiment, conn)
        
        logger.info(f"Found {len(extreme_checks['price_movements'])} extreme price movements (>20%)")
        
        return extreme_checks
    
    def generate_validation_report(self, output_path: str = 'data_quality_report.html'):
        """Generate comprehensive HTML validation report"""
        logger.info("Generating validation report...")
        
        # Run all checks
        sql_checks = self.run_all_validations()
        freshness = self.check_data_freshness()
        coverage = self.check_data_coverage()
        sentiment_dist = self.check_sentiment_distribution()
        duplicates = self.check_duplicate_records()
        gaps = self.check_time_series_gaps()
        extremes = self.check_extreme_values()
        
        # Create HTML report
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Data Quality Report - {datetime.now().strftime('%Y-%m-%d %H:%M')}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }}
                h1 {{ color: #333; }}
                h2 {{ color: #666; margin-top: 30px; }}
                .summary {{ background: white; padding: 20px; border-radius: 5px; margin: 20px 0; }}
                .pass {{ color: green; font-weight: bold; }}
                .fail {{ color: red; font-weight: bold; }}
                .warning {{ color: orange; font-weight: bold; }}
                table {{ border-collapse: collapse; width: 100%; background: white; margin: 10px 0; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #4CAF50; color: white; }}
                tr:nth-child(even) {{ background-color: #f2f2f2; }}
                .metric {{ display: inline-block; margin: 10px 20px; }}
                .metric-value {{ font-size: 24px; font-weight: bold; }}
                .metric-label {{ color: #666; }}
            </style>
        </head>
        <body>
            <h1>Data Quality Validation Report</h1>
            <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            
            <div class="summary">
                <h2>Summary</h2>
                <div class="metric">
                    <div class="metric-value pass">{len(sql_checks[sql_checks['status'] == 'pass'])}</div>
                    <div class="metric-label">Passed</div>
                </div>
                <div class="metric">
                    <div class="metric-value fail">{len(sql_checks[sql_checks['status'] == 'fail'])}</div>
                    <div class="metric-label">Failed</div>
                </div>
                <div class="metric">
                    <div class="metric-value warning">{len(sql_checks[sql_checks['status'] == 'warning'])}</div>
                    <div class="metric-label">Warnings</div>
                </div>
            </div>
            
            <h2>Failed Checks</h2>
            {sql_checks[sql_checks['status'] == 'fail'].to_html(index=False, classes='dataframe')}
            
            <h2>Warnings</h2>
            {sql_checks[sql_checks['status'] == 'warning'].to_html(index=False, classes='dataframe')}
            
            <h2>Data Freshness</h2>
            <table>
                <tr>
                    <th>Table</th>
                    <th>Latest Record</th>
                    <th>Hours Old</th>
                    <th>Status</th>
                </tr>
        """
        
        for check in freshness['results']:
            html += f"""
                <tr>
                    <td>{check['table']}</td>
                    <td>{check['latest_record']}</td>
                    <td>{check['hours_old']:.1f if check['hours_old'] else 'N/A'}</td>
                    <td class="{check['status']}">{check['status']}</td>
                </tr>
            """
        
        html += """
            </table>
            
            <h2>Ticker Coverage</h2>
        """
        
        html += coverage.head(20).to_html(index=False, classes='dataframe')
        
        html += f"""
            <h2>Duplicate Records</h2>
            <table>
                <tr>
                    <th>Table</th>
                    <th>Duplicate Keys</th>
                    <th>Total Duplicates</th>
                </tr>
        """
        
        for table, stats in duplicates.items():
            html += f"""
                <tr>
                    <td>{table}</td>
                    <td>{stats['duplicate_keys']}</td>
                    <td>{stats['total_duplicates']}</td>
                </tr>
            """
        
        html += """
            </table>
            
            <h2>Time Series Gaps</h2>
        """
        
        if len(gaps) > 0:
            html += gaps.head(20).to_html(index=False, classes='dataframe')
        else:
            html += "<p>No significant gaps found.</p>"
        
        html += """
        </body>
        </html>
        """
        
        # Write report
        with open(output_path, 'w') as f:
            f.write(html)
        
        logger.info(f"Report saved to {output_path}")
        
        return {
            'sql_checks': sql_checks,
            'freshness': freshness,
            'coverage': coverage,
            'sentiment_dist': sentiment_dist,
            'duplicates': duplicates,
            'gaps': gaps,
            'extremes': extremes
        }


def main():
    """Main execution function"""
    
    DB_CONFIG = {
        'dbname': os.getenv('DB_NAME'),
        'user': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASSWORD'),
        'host': os.getenv('DB_HOST'),
        'port': os.getenv('DB_PORT')
    }
    
    # Database connection string
    # Modify this with your actual connection details
    conn_string = f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}"
    
    # Initialize validator
    validator = DataQualityValidator(conn_string)
    
    # Generate full report
    results = validator.generate_validation_report('data_quality_report.html')
    
    # Print summary to console
    print("\n" + "="*60)
    print("DATA QUALITY VALIDATION SUMMARY")
    print("="*60)
    
    sql_checks = results['sql_checks']
    print(f"\nTotal Checks: {len(sql_checks)}")
    print(f"  ✓ Passed: {len(sql_checks[sql_checks['status'] == 'pass'])}")
    print(f"  ✗ Failed: {len(sql_checks[sql_checks['status'] == 'fail'])}")
    print(f"  ⚠ Warnings: {len(sql_checks[sql_checks['status'] == 'warning'])}")
    
    print("\nData Freshness:")
    for check in results['freshness']['results']:
        status_icon = "✓" if check['status'] == 'fresh' else "⚠"
        print(f"  {status_icon} {check['table']}: {check['status']}")
    
    print("\nDuplicate Records:")
    for table, stats in results['duplicates'].items():
        if stats['duplicate_keys'] > 0:
            print(f"  ⚠ {table}: {stats['duplicate_keys']} duplicate keys")
        else:
            print(f"  ✓ {table}: No duplicates")
    
    print(f"\nFull report saved to: data_quality_report.html")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
