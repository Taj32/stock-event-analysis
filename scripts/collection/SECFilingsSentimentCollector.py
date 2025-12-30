"""
SEC Filings sentiment collector using CSV data from SECFilingCollector
Analyzes sentiment from filing text and metadata
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


class SECFilingsSentimentCollector:
    """Collector for SEC filings sentiment analysis"""
    
    def __init__(self, csv_dir='data/raw/sec_filings', output_dir='data/processed/sec-sentiment'):
        """
        Initialize collector
        
        Args:
            csv_dir: Directory containing {ticker}_filings.csv files
            output_dir: Directory to save processed sentiment results
        """
        self.csv_dir = Path(csv_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Initialized SEC filings sentiment collector from: {self.csv_dir}")
        logger.info(f"Output directory: {self.output_dir}")
    
    def load_filings_for_ticker(self, ticker):
        """
        Load filings CSV for a specific ticker
        
        Args:
            ticker: Stock ticker symbol
        
        Returns:
            DataFrame with filings or empty DataFrame if file not found
        """
        csv_file = self.csv_dir / f"{ticker}_filings.csv"
        
        if not csv_file.exists():
            logger.warning(f"Filings file not found: {csv_file}")
            return pd.DataFrame()
        
        try:
            df = pd.read_csv(csv_file)
            logger.info(f"Loaded {len(df)} filings for {ticker} from {csv_file.name}")
            return df
        except Exception as e:
            logger.error(f"Failed to load {csv_file}: {e}")
            return pd.DataFrame()
    
    def classify_filing_sentiment(self, form_type, filing_date, category=None):
        """
        Classify sentiment based on filing type and characteristics
        
        Args:
            form_type: Form type (10-K, 10-Q, 8-K, etc.)
            filing_date: Date of filing
            category: 8-K category if applicable
        
        Returns:
            Sentiment score between -1 (negative) and 1 (positive)
        """
        sentiment = 0.0
        
        # Form type sentiment base (some forms more significant than others)
        form_sentiment = {
            '10-K': 0.0,   # Annual report - neutral baseline
            '10-Q': 0.0,   # Quarterly report - neutral baseline
            '8-K': -0.1,   # Material event - slight negative bias (major changes)
            '4': -0.2,     # Insider trading - negative (uncertainty)
            '5': -0.15,    # Insider trading (delayed) - negative
            '6-K': -0.1,   # Foreign private issuer event
            '11-K': 0.0,   # Annual report of employee stock plan
            '20-F': 0.0,   # Annual report (foreign)
            'S-1': 0.0,    # Registration statement
            'DEF14A': 0.0,  # Proxy statement
        }
        
        sentiment = form_sentiment.get(form_type, 0.0)
        
        # 8-K specific categorization
        if form_type == '8-K' and category:
            category_sentiment = {
                'Bankruptcy': -0.8,
                'Bankruptcy - Default': -0.9,
                'Bankruptcy - Emergence': 0.2,
                'Costs Associated with Exit or Disposal': -0.5,
                'Creation of a Direct Financial Obligation': -0.3,
                'Decrease in Assets': -0.4,
                'Directorship or Executive Officer Changes': -0.1,
                'Material Agreements': 0.1,
                'Material Impairments': -0.6,
                'Other Events': -0.05,
                'Patent-Related Events': 0.1,
                'Unregister or Delisting': -0.7,
                'Merger or Acquisition': 0.2,  # Acquisition could be positive or negative
                'Earnings': 0.0,  # Neutral - depends on actual earnings
                'Management Change': -0.15,
            }
            
            category_sentiment_value = category_sentiment.get(category, -0.05)
            sentiment = (sentiment + category_sentiment_value) / 2
        
        # Clamp to [-1, 1]
        return max(-1.0, min(1.0, sentiment))
    
    def process_filings_for_ticker(self, df, ticker):
        """
        Process all filings for a specific ticker
        
        Args:
            df: DataFrame with filings
            ticker: Stock ticker symbol
        
        Returns:
            List of filing dictionaries with sentiment
        """
        if df.empty:
            return []
        
        logger.info(f"Processing {len(df)} filings for {ticker}...")
        
        filings = []
        
        for idx, row in df.iterrows():
            try:
                form_type = str(row.get('form', '')).strip() if pd.notna(row.get('form')) else ''
                filing_date = row.get('filingDate') if pd.notna(row.get('filingDate')) else None
                category = str(row.get('category', '')).strip() if pd.notna(row.get('category')) else None
                url = str(row.get('filing_url', '')) if pd.notna(row.get('filing_url')) else ''
                accession_number = str(row.get('accessionNumber', '')) if pd.notna(row.get('accessionNumber')) else ''
                primary_doc = str(row.get('primaryDocument', '')) if pd.notna(row.get('primaryDocument')) else ''
                
                # Parse filing date
                try:
                    filing_dt = pd.to_datetime(filing_date)
                except:
                    logger.warning(f"Could not parse date: {filing_date}")
                    continue
                
                # Skip category field if it's 'Other' (placeholder)
                category_value = category if category and category != 'Other' else None
                
                # Calculate sentiment
                sentiment = self.classify_filing_sentiment(form_type, filing_dt, category_value)
                
                filing_data = {
                    'filed_at': filing_dt,
                    'form_type': form_type,
                    'accession_number': accession_number,
                    'category': category_value,
                    'primary_document': primary_doc,
                    'url': url,
                    'sentiment': sentiment
                }
                
                filings.append(filing_data)
            
            except Exception as e:
                logger.warning(f"Error processing filing at row {idx}: {e}")
                continue
        
        logger.info(f"Processed {len(filings)} filings for {ticker}")
        return filings
    
    def aggregate_daily_sentiment(self, filings, ticker):
        """
        Aggregate filings into daily sentiment metrics by form type
        
        Args:
            filings: List of filing dictionaries
            ticker: Stock ticker
        
        Returns:
            DataFrame with daily aggregated sentiment
        """
        if not filings:
            return pd.DataFrame()
        
        df = pd.DataFrame(filings)
        df['date'] = pd.to_datetime(df['filed_at']).dt.date
        
        # Group by date
        daily = df.groupby('date').agg({
            'form_type': 'count',  # Use form_type for count
            'sentiment': 'mean',
            'accession_number': 'nunique'  # Count unique filings
        }).reset_index()
        
        # Flatten column names
        daily.columns = ['date', 'filing_count', 'avg_sentiment', 'unique_filings']
        
        # Calculate sentiment distribution
        positive_counts = df[df['sentiment'] > 0.1].groupby('date').size()
        negative_counts = df[df['sentiment'] < -0.1].groupby('date').size()
        neutral_counts = df[(df['sentiment'] >= -0.1) & (df['sentiment'] <= 0.1)].groupby('date').size()
        
        daily['positive_count'] = daily['date'].map(positive_counts).fillna(0).astype(int)
        daily['negative_count'] = daily['date'].map(negative_counts).fillna(0).astype(int)
        daily['neutral_count'] = daily['date'].map(neutral_counts).fillna(0).astype(int)
        
        # Form type breakdown
        form_counts = df.groupby(['date', 'form_type']).size().unstack(fill_value=0)
        for form in form_counts.columns:
            daily[f'{form}_count'] = daily['date'].map(
                df[df['form_type'] == form].groupby('date').size()
            ).fillna(0).astype(int)
        
        # Add ticker
        daily['ticker'] = ticker
        
        # Sort by date
        daily = daily.sort_values('date').reset_index(drop=True)
        
        return daily
    
    def save_filings(self, filings, ticker):
        """Save individual filings to JSON"""
        output_file = self.output_dir / f"{ticker}_filings_sentiment.json"
        
        # Convert datetime to string for JSON serialization
        filings_serializable = []
        for filing in filings:
            filing_copy = filing.copy()
            filing_copy['filed_at'] = filing_copy['filed_at'].isoformat()
            filings_serializable.append(filing_copy)
        
        with open(output_file, 'w') as f:
            json.dump(filings_serializable, f, indent=2)
        
        logger.info(f"Saved {len(filings)} filings to {output_file}")
    
    def save_daily_sentiment(self, df, ticker):
        """Save daily aggregated sentiment to CSV"""
        output_file = self.output_dir / f"{ticker}_daily_sentiment.csv"
        df.to_csv(output_file, index=False)
        logger.info(f"Saved daily sentiment to {output_file}")
    
    def collect_for_ticker(self, ticker, save_filings_detail=True):
        """
        Collect SEC filings sentiment for a ticker
        
        Args:
            ticker: Stock ticker
            save_filings_detail: Whether to save individual filings
        
        Returns:
            Dictionary with status and aggregated data
        """
        try:
            # Load filings for this ticker
            df = self.load_filings_for_ticker(ticker)
            
            if df.empty:
                return {
                    'ticker': ticker,
                    'status': 'no_data',
                    'total_filings': 0
                }
            
            # Process filings
            filings = self.process_filings_for_ticker(df, ticker)
            
            if not filings:
                return {
                    'ticker': ticker,
                    'status': 'no_data',
                    'total_filings': 0
                }
            
            # Save individual filings if requested
            if save_filings_detail:
                self.save_filings(filings, ticker)
            
            # Aggregate daily sentiment
            daily_sentiment = self.aggregate_daily_sentiment(filings, ticker)
            
            # Save aggregated data
            self.save_daily_sentiment(daily_sentiment, ticker)
            
            # Count by form type
            form_counts = {}
            for filing in filings:
                form_type = filing['form_type']
                form_counts[form_type] = form_counts.get(form_type, 0) + 1
            
            return {
                'ticker': ticker,
                'status': 'success',
                'total_filings': len(filings),
                'by_form_type': form_counts,
                'date_range': {
                    'earliest': daily_sentiment['date'].min().strftime('%Y-%m-%d'),
                    'latest': daily_sentiment['date'].max().strftime('%Y-%m-%d')
                },
                'avg_daily_filings': daily_sentiment['filing_count'].mean(),
                'avg_sentiment': daily_sentiment['avg_sentiment'].mean()
            }
            
        except Exception as e:
            logger.error(f"Failed to collect SEC filings sentiment for {ticker}: {str(e)}")
            return {
                'ticker': ticker,
                'status': 'failed',
                'error': str(e)
            }
    
    def collect_for_multiple_tickers(self, tickers, save_filings_detail=True):
        """
        Collect SEC filings sentiment for multiple tickers
        
        Args:
            tickers: List of ticker symbols
            save_filings_detail: Whether to save individual filings
        
        Returns:
            List of results for each ticker
        """
        results = []
        
        for i, ticker in enumerate(tickers, 1):
            logger.info(f"Processing {ticker} ({i}/{len(tickers)})")
            
            result = self.collect_for_ticker(
                ticker,
                save_filings_detail=save_filings_detail
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
    collector = SECFilingsSentimentCollector(
        csv_dir='data/raw/sec_filings',
        output_dir='data/processed/sec-sentiment'
    )
    
    # Test with available tickers
    tickers = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'META', 'JPM', 'AMD']
    
    print(f"\nCollecting SEC filings sentiment for {len(tickers)} stocks")
    print(f"From filings in: {collector.csv_dir}\n")
    
    results = collector.collect_for_multiple_tickers(
        tickers,
        save_filings_detail=True
    )
    
    # Print summary
    print("\n" + "="*60)
    print("SEC FILINGS SENTIMENT COLLECTION RESULTS")
    print("="*60)
    for result in results:
        print(f"\n{result['ticker']}: {result['status']}")
        if result['status'] == 'success':
            print(f"  Total filings: {result['total_filings']}")
            print(f"  By form type: {result['by_form_type']}")
            print(f"  Date range: {result['date_range']['earliest']} to {result['date_range']['latest']}")
            print(f"  Avg daily filings: {result['avg_daily_filings']:.1f}")
            print(f"  Avg sentiment: {result['avg_sentiment']:.2f}")


if __name__ == '__main__':
    main()
