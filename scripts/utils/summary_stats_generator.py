"""
Summary Statistics and Data Availability Report Generator
Generates comprehensive reports on data coverage, distributions, and quality
"""

from dotenv import load_dotenv
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime
import psycopg2
from io import BytesIO
import base64
import warnings
import os

load_dotenv()
warnings.filterwarnings('ignore')


# Set style for visualizations
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (12, 6)


class SummaryStatisticsGenerator:
    """Generate summary statistics and availability reports"""
    
    def __init__(self, connection_string: str):
        self.conn_string = connection_string
        
    def get_connection(self):
        return psycopg2.connect(self.conn_string)
    
    def get_overall_stats(self) -> pd.DataFrame:
        """Get high-level database statistics"""
        query = "SELECT * FROM summary_overall_stats"
        with self.get_connection() as conn:
            return pd.read_sql(query, conn)
    
    def get_ticker_availability(self) -> pd.DataFrame:
        """Get data availability by ticker"""
        query = "SELECT * FROM summary_ticker_availability"
        with self.get_connection() as conn:
            return pd.read_sql(query, conn)
    
    def get_time_series_density(self) -> pd.DataFrame:
        """Get monthly data density"""
        query = "SELECT * FROM summary_time_series_density ORDER BY month"
        with self.get_connection() as conn:
            df = pd.read_sql(query, conn)
            df['month'] = pd.to_datetime(df['month'])
            return df
    
    def get_sentiment_stats(self) -> pd.DataFrame:
        """Get sentiment distribution statistics"""
        query = "SELECT * FROM summary_sentiment_stats"
        with self.get_connection() as conn:
            return pd.read_sql(query, conn)
    
    def get_price_stats(self) -> pd.DataFrame:
        """Get price statistics by ticker"""
        query = "SELECT * FROM summary_price_stats"
        with self.get_connection() as conn:
            return pd.read_sql(query, conn)
    
    def get_ticker_activity(self) -> pd.DataFrame:
        """Get ticker activity rankings"""
        query = "SELECT * FROM summary_ticker_activity"
        with self.get_connection() as conn:
            return pd.read_sql(query, conn)
    
    def get_data_gaps(self) -> pd.DataFrame:
        """Get data gap report"""
        query = "SELECT * FROM summary_data_gaps"
        with self.get_connection() as conn:
            return pd.read_sql(query, conn)
    
    def get_sector_stats(self) -> pd.DataFrame:
        """Get sector-level statistics"""
        query = "SELECT * FROM summary_sector_stats"
        with self.get_connection() as conn:
            return pd.read_sql(query, conn)
    
    def get_recent_activity(self) -> pd.DataFrame:
        """Get recent daily activity"""
        query = "SELECT * FROM summary_recent_activity"
        with self.get_connection() as conn:
            df = pd.read_sql(query, conn)
            df['date'] = pd.to_datetime(df['date'])
            return df
    
    def plot_to_base64(self, fig) -> str:
        """Convert matplotlib figure to base64 string for HTML embedding"""
        buf = BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight', dpi=100)
        buf.seek(0)
        img_str = base64.b64encode(buf.read()).decode()
        plt.close(fig)
        return f"data:image/png;base64,{img_str}"
    
    def create_time_series_plot(self, df: pd.DataFrame) -> str:
        """Create time series density visualization"""
        fig, axes = plt.subplots(2, 2, figsize=(15, 10))
        
        # Price records over time
        axes[0, 0].plot(df['month'], df['price_records'], marker='o', linewidth=2)
        axes[0, 0].set_title('Stock Price Records Over Time', fontsize=12, fontweight='bold')
        axes[0, 0].set_xlabel('Month')
        axes[0, 0].set_ylabel('Number of Records')
        axes[0, 0].grid(True, alpha=0.3)
        
        # Reddit posts over time
        axes[0, 1].plot(df['month'], df['reddit_posts'], marker='o', color='orange', linewidth=2)
        axes[0, 1].set_title('Reddit Posts Over Time', fontsize=12, fontweight='bold')
        axes[0, 1].set_xlabel('Month')
        axes[0, 1].set_ylabel('Number of Posts')
        axes[0, 1].grid(True, alpha=0.3)
        
        # News articles over time
        axes[1, 0].plot(df['month'], df['news_articles'], marker='o', color='green', linewidth=2)
        axes[1, 0].set_title('News Articles Over Time', fontsize=12, fontweight='bold')
        axes[1, 0].set_xlabel('Month')
        axes[1, 0].set_ylabel('Number of Articles')
        axes[1, 0].grid(True, alpha=0.3)
        
        # SEC filings over time
        axes[1, 1].plot(df['month'], df['sec_filings'], marker='o', color='red', linewidth=2)
        axes[1, 1].set_title('SEC Filings Over Time', fontsize=12, fontweight='bold')
        axes[1, 1].set_xlabel('Month')
        axes[1, 1].set_ylabel('Number of Filings')
        axes[1, 1].grid(True, alpha=0.3)
        
        plt.tight_layout()
        return self.plot_to_base64(fig)
    
    def create_sentiment_distribution_plot(self, df: pd.DataFrame) -> str:
        """Create sentiment distribution comparison"""
        fig, axes = plt.subplots(1, 2, figsize=(15, 5))
        
        # Distribution comparison
        sources = df['source'].tolist()
        x = np.arange(len(sources))
        width = 0.25
        
        axes[0].bar(x - width, df['positive_count'], width, label='Positive', color='green', alpha=0.7)
        axes[0].bar(x, df['neutral_count'], width, label='Neutral', color='gray', alpha=0.7)
        axes[0].bar(x + width, df['negative_count'], width, label='Negative', color='red', alpha=0.7)
        axes[0].set_xlabel('Source')
        axes[0].set_ylabel('Count')
        axes[0].set_title('Sentiment Distribution by Source', fontweight='bold')
        axes[0].set_xticks(x)
        axes[0].set_xticklabels(sources)
        axes[0].legend()
        axes[0].grid(True, alpha=0.3)
        
        # Mean sentiment comparison
        axes[1].barh(sources, df['mean_score'], color=['orange', 'green', 'red'])
        axes[1].set_xlabel('Mean Sentiment Score')
        axes[1].set_title('Average Sentiment by Source', fontweight='bold')
        axes[1].axvline(x=0, color='black', linestyle='--', linewidth=1)
        axes[1].grid(True, alpha=0.3)
        
        plt.tight_layout()
        return self.plot_to_base64(fig)
    
    def create_ticker_coverage_plot(self, df: pd.DataFrame, top_n: int = 15) -> str:
        """Create ticker data coverage visualization"""
        top_tickers = df.head(top_n)
        
        fig, ax = plt.subplots(figsize=(12, 8))
        
        x = np.arange(len(top_tickers))
        width = 0.2
        
        ax.bar(x - width*1.5, top_tickers['price_days'], width, label='Price Days', alpha=0.8)
        ax.bar(x - width/2, top_tickers['reddit_posts'], width, label='Reddit Posts', alpha=0.8)
        ax.bar(x + width/2, top_tickers['news_articles'], width, label='News Articles', alpha=0.8)
        ax.bar(x + width*1.5, top_tickers['sec_filings'], width, label='SEC Filings', alpha=0.8)
        
        ax.set_xlabel('Ticker Symbol', fontweight='bold')
        ax.set_ylabel('Count', fontweight='bold')
        ax.set_title(f'Top {top_n} Tickers by Data Coverage', fontsize=14, fontweight='bold')
        ax.set_xticks(x)
        ax.set_xticklabels(top_tickers['symbol'], rotation=45, ha='right')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        return self.plot_to_base64(fig)
    
    def create_sector_comparison_plot(self, df: pd.DataFrame) -> str:
        """Create sector comparison visualization"""
        if len(df) == 0:
            return ""
        
        fig, axes = plt.subplots(2, 2, figsize=(15, 10))
        
        # Ticker count by sector
        df_sorted = df.sort_values('ticker_count', ascending=True)
        axes[0, 0].barh(df_sorted['sector'], df_sorted['ticker_count'], color='steelblue')
        axes[0, 0].set_xlabel('Number of Tickers')
        axes[0, 0].set_title('Tickers per Sector', fontweight='bold')
        axes[0, 0].grid(True, alpha=0.3)
        
        # Average returns by sector
        df_sorted = df.sort_values('avg_daily_return_pct', ascending=True)
        colors = ['red' if x < 0 else 'green' for x in df_sorted['avg_daily_return_pct']]
        axes[0, 1].barh(df_sorted['sector'], df_sorted['avg_daily_return_pct'], color=colors, alpha=0.7)
        axes[0, 1].set_xlabel('Average Daily Return (%)')
        axes[0, 1].set_title('Average Returns by Sector', fontweight='bold')
        axes[0, 1].axvline(x=0, color='black', linestyle='--', linewidth=1)
        axes[0, 1].grid(True, alpha=0.3)
        
        # Social media mentions
        axes[1, 0].bar(df['sector'], df['total_reddit_mentions'], alpha=0.7, color='orange')
        axes[1, 0].set_xlabel('Sector')
        axes[1, 0].set_ylabel('Reddit Mentions')
        axes[1, 0].set_title('Reddit Activity by Sector', fontweight='bold')
        axes[1, 0].tick_params(axis='x', rotation=45)
        axes[1, 0].grid(True, alpha=0.3)
        
        # News coverage
        axes[1, 1].bar(df['sector'], df['total_news_articles'], alpha=0.7, color='green')
        axes[1, 1].set_xlabel('Sector')
        axes[1, 1].set_ylabel('News Articles')
        axes[1, 1].set_title('News Coverage by Sector', fontweight='bold')
        axes[1, 1].tick_params(axis='x', rotation=45)
        axes[1, 1].grid(True, alpha=0.3)
        
        plt.tight_layout()
        return self.plot_to_base64(fig)
    
    def generate_html_report(self, output_path: str = 'summary_statistics_report.html'):
        """Generate comprehensive HTML report"""
        print("Generating summary statistics report...")
        
        # Fetch all data
        overall = self.get_overall_stats()
        ticker_avail = self.get_ticker_availability()
        time_series = self.get_time_series_density()
        sentiment = self.get_sentiment_stats()
        prices = self.get_price_stats()
        activity = self.get_ticker_activity()
        gaps = self.get_data_gaps()
        sectors = self.get_sector_stats()
        recent = self.get_recent_activity()
        
        # Create visualizations
        print("Creating visualizations...")
        ts_plot = self.create_time_series_plot(time_series)
        sentiment_plot = self.create_sentiment_distribution_plot(sentiment)
        coverage_plot = self.create_ticker_coverage_plot(ticker_avail)
        sector_plot = self.create_sector_comparison_plot(sectors)
        
        # Build HTML
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Summary Statistics Report - {datetime.now().strftime('%Y-%m-%d')}</title>
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    margin: 20px;
                    background-color: #f5f5f5;
                    color: #333;
                }}
                h1 {{
                    color: #2c3e50;
                    border-bottom: 3px solid #3498db;
                    padding-bottom: 10px;
                }}
                h2 {{
                    color: #34495e;
                    margin-top: 40px;
                    border-left: 4px solid #3498db;
                    padding-left: 10px;
                }}
                h3 {{
                    color: #7f8c8d;
                    margin-top: 20px;
                }}
                .summary-box {{
                    background: white;
                    padding: 20px;
                    border-radius: 8px;
                    margin: 20px 0;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                .metric-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 20px;
                    margin: 20px 0;
                }}
                .metric-card {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 20px;
                    border-radius: 8px;
                    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                }}
                .metric-value {{
                    font-size: 32px;
                    font-weight: bold;
                    margin: 10px 0;
                }}
                .metric-label {{
                    font-size: 14px;
                    opacity: 0.9;
                    text-transform: uppercase;
                }}
                table {{
                    border-collapse: collapse;
                    width: 100%;
                    background: white;
                    margin: 20px 0;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                th, td {{
                    border: 1px solid #ddd;
                    padding: 12px;
                    text-align: left;
                }}
                th {{
                    background-color: #3498db;
                    color: white;
                    font-weight: bold;
                }}
                tr:nth-child(even) {{
                    background-color: #f8f9fa;
                }}
                tr:hover {{
                    background-color: #e3f2fd;
                }}
                .chart-container {{
                    background: white;
                    padding: 20px;
                    border-radius: 8px;
                    margin: 20px 0;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                img {{
                    max-width: 100%;
                    height: auto;
                }}
                .excellent {{ color: #27ae60; font-weight: bold; }}
                .good {{ color: #2ecc71; }}
                .moderate {{ color: #f39c12; }}
                .limited {{ color: #e74c3c; }}
                .timestamp {{
                    color: #7f8c8d;
                    font-style: italic;
                }}
            </style>
        </head>
        <body>
            <h1>📊 Summary Statistics & Data Availability Report</h1>
            <p class="timestamp">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            
            <div class="summary-box">
                <h2>📈 Database Overview</h2>
                <div class="metric-grid">
        """
        
        # Add metric cards for key stats
        key_metrics = {
            'Tickers': overall[overall['metric'] == 'Tickers']['value'].iloc[0],
            'Stock Prices': overall[overall['metric'] == 'Stock Prices']['value'].iloc[0],
            'Reddit Posts': overall[overall['metric'] == 'Reddit Posts']['value'].iloc[0],
            'News Articles': overall[overall['metric'] == 'News Articles']['value'].iloc[0],
            'SEC Filings': overall[overall['metric'] == 'SEC Filings']['value'].iloc[0]
        }
        
        for label, value in key_metrics.items():
            html += f"""
                    <div class="metric-card">
                        <div class="metric-label">{label}</div>
                        <div class="metric-value">{value}</div>
                    </div>
            """
        
        html += """
                </div>
            </div>
            
            <div class="chart-container">
                <h2>📅 Data Collection Timeline</h2>
                <img src="{}" alt="Time Series Density">
            </div>
            
            <div class="summary-box">
                <h2>🎯 Top Tickers by Data Coverage</h2>
                {}
            </div>
            
            <div class="chart-container">
                <img src="{}" alt="Ticker Coverage">
            </div>
            
            <div class="summary-box">
                <h2>💭 Sentiment Analysis Summary</h2>
                {}
            </div>
            
            <div class="chart-container">
                <img src="{}" alt="Sentiment Distribution">
            </div>
            
            <div class="summary-box">
                <h2>📊 Price Statistics (Top 10 by Trading Days)</h2>
                {}
            </div>
            
            <div class="summary-box">
                <h2>🔥 Most Active Tickers (Top 15)</h2>
                {}
            </div>
            
            <div class="summary-box">
                <h2>🏢 Sector Analysis</h2>
                {}
            </div>
            
            <div class="chart-container">
                <img src="{}" alt="Sector Comparison">
            </div>
            
            <div class="summary-box">
                <h2>⚠️ Data Gaps (>5 days)</h2>
                {}
            </div>
            
            <div class="summary-box">
                <h2>📆 Recent Activity (Last 30 Days)</h2>
                {}
            </div>
            
        </body>
        </html>
        """.format(
            ts_plot,
            ticker_avail.head(10).to_html(index=False, classes='dataframe'),
            coverage_plot,
            sentiment.to_html(index=False, classes='dataframe'),
            sentiment_plot,
            prices.head(10).to_html(index=False, classes='dataframe'),
            activity.head(15).to_html(index=False, classes='dataframe'),
            sectors.to_html(index=False, classes='dataframe'),
            sector_plot,
            gaps.head(20).to_html(index=False, classes='dataframe') if len(gaps) > 0 else "<p>No significant gaps found!</p>",
            recent.head(30).to_html(index=False, classes='dataframe')
        )
        
        # Write report
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
        
        print(f"✓ Report saved to {output_path}")
        
        return {
            'overall': overall,
            'ticker_availability': ticker_avail,
            'sentiment': sentiment,
            'prices': prices,
            'activity': activity,
            'gaps': gaps,
            'sectors': sectors
        }


def main():
    """Main execution"""
    # Database connection
    
    DB_CONFIG = {
        'dbname': os.getenv('DB_NAME'),
        'user': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASSWORD'),
        'host': os.getenv('DB_HOST'),
        'port': os.getenv('DB_PORT')
    }
    
    conn_string = f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}"
    
    # Generate report
    generator = SummaryStatisticsGenerator(conn_string)
    results = generator.generate_html_report('summary_statistics_report.html')
    
    # Print summary to console
    print("\n" + "="*70)
    print("SUMMARY STATISTICS REPORT GENERATED")
    print("="*70)
    
    overall = results['overall']
    print("\nDatabase Totals:")
    for _, row in overall.iterrows():
        print(f"  {row['metric']}: {row['value']}")
    
    print("\nTop 5 Tickers by Coverage:")
    top5 = results['ticker_availability'].head(5)
    for _, row in top5.iterrows():
        print(f"  {row['symbol']}: {row['price_days']} price days, "
              f"{row['reddit_posts']} Reddit, {row['news_articles']} news - {row['overall_data_quality']}")
    
    print("\nSentiment Summary:")
    for _, row in results['sentiment'].iterrows():
        print(f"  {row['source']}: Mean={row['mean_score']:.3f}, "
              f"Pos={row['positive_count']}, Neg={row['negative_count']}")
    
    print("\n" + "="*70)
    print("Full report: summary_statistics_report.html")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
