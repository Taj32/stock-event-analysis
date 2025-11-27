"""
Earnings data collector using Alpha Vantage
"""
import requests
import json
import os
import pandas as pd
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import sys
sys.path.append(str(Path(__file__).parent.parent))

from utils.rate_limiter import alpha_vantage_limiter
from utils.error_handler import safe_api_call, create_logger, handle_response, DataNotFoundError

load_dotenv()
logger = create_logger(__name__)


class EarningsCollector:
    """Collector for earnings data from Alpha Vantage"""
    
    def __init__(self, api_key=None, output_dir='data/raw/earnings'):
        self.api_key = api_key or os.getenv('ALPHA_VANTAGE_API_KEY')
        if not self.api_key:
            raise ValueError("Alpha Vantage API key not found. Set ALPHA_VANTAGE_API_KEY in .env")
        
        self.base_url = 'https://www.alphavantage.co/query'
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    @alpha_vantage_limiter
    @safe_api_call
    def fetch_earnings(self, ticker):
        """
        Fetch earnings data for a ticker
        
        Args:
            ticker: Stock ticker symbol
        
        Returns:
            Dictionary with quarterly and annual earnings
        """
        logger.info(f"Fetching earnings for {ticker}")
        
        params = {
            'function': 'EARNINGS',
            'symbol': ticker,
            'apikey': self.api_key
        }
        
        response = requests.get(self.base_url, params=params)
        data = handle_response(response, "Alpha Vantage")
        
        # Check if we got valid data
        if 'quarterlyEarnings' not in data:
            if 'Note' in data:
                logger.warning(f"API limit message: {data['Note']}")
                raise Exception("API call limit reached")
            elif 'Error Message' in data:
                raise DataNotFoundError(f"Ticker {ticker} not found")
            else:
                raise Exception(f"Unexpected response format: {data}")
        
        logger.info(f"Successfully fetched earnings for {ticker}")
        return data
    
    def parse_earnings(self, raw_data, ticker):
        """
        Parse raw earnings data into structured format
        
        Args:
            raw_data: Raw API response
            ticker: Stock ticker symbol
        
        Returns:
            DataFrame with parsed earnings
        """
        quarterly = raw_data.get('quarterlyEarnings', [])
        
        if not quarterly:
            logger.warning(f"No quarterly earnings found for {ticker}")
            return pd.DataFrame()
        
        # Convert to DataFrame
        df = pd.DataFrame(quarterly)
        
        # Add ticker column
        df['ticker'] = ticker
        
        # Convert numeric columns
        numeric_cols = ['reportedEPS', 'estimatedEPS', 'surprise', 'surprisePercentage']
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Calculate surprise if not provided
        if 'surprise' not in df.columns or df['surprise'].isna().all():
            df['surprise'] = df['reportedEPS'] - df['estimatedEPS']
        
        if 'surprisePercentage' not in df.columns or df['surprisePercentage'].isna().all():
            df['surprisePercentage'] = (df['surprise'] / df['estimatedEPS'].abs()) * 100
        
        # Convert dates
        df['fiscalDateEnding'] = pd.to_datetime(df['fiscalDateEnding'])
        df['reportedDate'] = pd.to_datetime(df['reportedDate'])
        
        # Rename columns for consistency
        df = df.rename(columns={
            'fiscalDateEnding': 'fiscal_date',
            'reportedDate': 'report_date',
            'reportedEPS': 'actual_eps',
            'estimatedEPS': 'estimated_eps',
            'surprise': 'surprise',
            'surprisePercentage': 'surprise_pct'
        })
        
        # Sort by date (most recent first)
        df = df.sort_values('report_date', ascending=False)
        
        # Select relevant columns
        df = df[['ticker', 'report_date', 'fiscal_date', 'actual_eps', 
                 'estimated_eps', 'surprise', 'surprise_pct']]
        
        return df
    
    def save_earnings(self, df, ticker):
        """
        Save earnings data to CSV
        
        Args:
            df: DataFrame with earnings data
            ticker: Stock ticker symbol
        """
        output_file = self.output_dir / f"{ticker}_earnings.csv"
        df.to_csv(output_file, index=False)
        logger.info(f"Saved earnings data to {output_file}")
    
    def save_raw_response(self, data, ticker):
        """
        Save raw API response to JSON
        
        Args:
            data: Raw API response
            ticker: Stock ticker symbol
        """
        output_file = self.output_dir / f"{ticker}_earnings_raw.json"
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved raw earnings data to {output_file}")
    
    def collect_for_ticker(self, ticker, save_raw=True):
        """
        Collect earnings data for a single ticker
        
        Args:
            ticker: Stock ticker symbol
            save_raw: Whether to save raw API response
        
        Returns:
            Dictionary with status and data
        """
        try:
            # Fetch data
            raw_data = self.fetch_earnings(ticker)
            
            # Save raw response if requested
            if save_raw:
                self.save_raw_response(raw_data, ticker)
            
            # Parse and save
            df = self.parse_earnings(raw_data, ticker)
            
            if df.empty:
                return {
                    'ticker': ticker,
                    'status': 'no_data',
                    'records': 0
                }
            
            self.save_earnings(df, ticker)
            
            return {
                'ticker': ticker,
                'status': 'success',
                'records': len(df),
                'date_range': {
                    'earliest': df['report_date'].min().strftime('%Y-%m-%d'),
                    'latest': df['report_date'].max().strftime('%Y-%m-%d')
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to collect earnings for {ticker}: {str(e)}")
            return {
                'ticker': ticker,
                'status': 'failed',
                'error': str(e)
            }
    
    def collect_for_multiple_tickers(self, tickers, save_raw=True):
        """
        Collect earnings for multiple tickers
        
        IMPORTANT: With free tier (25 calls/day), be careful!
        
        Args:
            tickers: List of ticker symbols
            save_raw: Whether to save raw responses
        
        Returns:
            List of results for each ticker
        """
        results = []
        
        logger.warning(f"About to make {len(tickers)} API calls to Alpha Vantage")
        logger.warning(f"Free tier limit: 25 calls/day. Current batch: {len(tickers)}")
        
        for i, ticker in enumerate(tickers, 1):
            logger.info(f"Processing {ticker} ({i}/{len(tickers)})")
            result = self.collect_for_ticker(ticker, save_raw)
            results.append(result)
            
            # Log progress
            if i % 5 == 0:
                successful = sum(1 for r in results if r['status'] == 'success')
                logger.info(f"Progress: {i}/{len(tickers)}, {successful} successful so far")
        
        # Final summary
        successful = sum(1 for r in results if r['status'] == 'success')
        failed = sum(1 for r in results if r['status'] == 'failed')
        no_data = sum(1 for r in results if r['status'] == 'no_data')
        
        logger.info(f"Completed: {successful} success, {failed} failed, {no_data} no data")
        logger.info(f"Total API calls used: {len(tickers)}")
        
        return results


def main():
    """Example usage"""
    collector = EarningsCollector()
    
    # Test with small batch (be mindful of API limits!)
    tickers = ['AAPL', 'MSFT', 'GOOGL']
    
    print(f"WARNING: About to use {len(tickers)} of your 25 daily API calls")
    print("Continue? (yes/no): ", end='')
    
    #Uncomment to actually run:
    response = input()
    if response.lower() == 'yes':
        results = collector.collect_for_multiple_tickers(tickers)
        
        for result in results:
            print(f"\n{result['ticker']}: {result['status']}")
            if result['status'] == 'success':
                print(f"  Records: {result['records']}")
                print(f"  Date range: {result['date_range']}")
    
    #print("Skipping actual collection (uncomment code to run)")


if __name__ == '__main__':
    main()