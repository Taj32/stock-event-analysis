"""
Stock price data collector using yfinance
"""
import yfinance as yf
import pandas as pd
import json
from pathlib import Path
from datetime import datetime
import sys
sys.path.append(str(Path(__file__).parent.parent))

from utils.rate_limiter import yfinance_limiter
from utils.error_handler import safe_api_call, create_logger, DataNotFoundError
from utils.date_utils import format_date

logger = create_logger(__name__)


class StockPriceCollector:
    """Collector for stock price data from yfinance"""
    
    def __init__(self, output_dir='data/raw/prices'):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    @yfinance_limiter
    @safe_api_call
    def fetch_historical_prices(self, ticker, start_date, end_date):
        """
        Fetch historical daily prices for a ticker
        
        Args:
            ticker: Stock ticker symbol (e.g., 'AAPL')
            start_date: Start date (YYYY-MM-DD string or datetime)
            end_date: End date (YYYY-MM-DD string or datetime)
        
        Returns:
            DataFrame with price data
        """
        logger.info(f"Fetching prices for {ticker} from {start_date} to {end_date}")
        
        # Download data
        ticker_obj = yf.Ticker(ticker)
        df = ticker_obj.history(start=start_date, end=end_date)
        
        if df.empty:
            raise DataNotFoundError(f"No price data found for {ticker}")
        
        # Clean up DataFrame
        df.reset_index(inplace=True)
        df['Ticker'] = ticker
        
        # Rename columns to match our schema
        df = df.rename(columns={
            'Date': 'date',
            'Open': 'open',
            'High': 'high',
            'Low': 'low',
            'Close': 'close',
            'Volume': 'volume',
            'Dividends': 'dividends',
            'Stock Splits': 'stock_splits'
        })
        
        # Select relevant columns
        df = df[['date', 'Ticker', 'open', 'high', 'low', 'close', 'volume', 
                 'dividends', 'stock_splits']]
        
        logger.info(f"Successfully fetched {len(df)} days of price data for {ticker}")
        return df
    
    @yfinance_limiter
    @safe_api_call
    def fetch_company_info(self, ticker):
        """
        Fetch company information
        
        Args:
            ticker: Stock ticker symbol
        
        Returns:
            Dictionary with company info
        """
        logger.info(f"Fetching company info for {ticker}")
        
        ticker_obj = yf.Ticker(ticker)
        info = ticker_obj.info
        
        # Extract relevant fields
        company_info = {
            'ticker': ticker,
            'name': info.get('longName', ''),
            'sector': info.get('sector', ''),
            'industry': info.get('industry', ''),
            'market_cap': info.get('marketCap', 0),
            'country': info.get('country', ''),
            'website': info.get('website', ''),
            'description': info.get('longBusinessSummary', ''),
            'collected_at': datetime.now().isoformat()
        }
        
        logger.info(f"Successfully fetched info for {ticker}")
        return company_info
    
    def save_prices(self, df, ticker):
        """
        Save price data to CSV file
        
        Args:
            df: DataFrame with price data
            ticker: Stock ticker symbol
        """
        output_file = self.output_dir / f"{ticker}_prices.csv"
        df.to_csv(output_file, index=False)
        logger.info(f"Saved price data to {output_file}")
    
    def save_company_info(self, info, ticker):
        """
        Save company info to JSON file
        
        Args:
            info: Dictionary with company info
            ticker: Stock ticker symbol
        """
        output_file = self.output_dir / f"{ticker}_info.json"
        with open(output_file, 'w') as f:
            json.dump(info, f, indent=2)
        logger.info(f"Saved company info to {output_file}")
    
    def collect_for_ticker(self, ticker, start_date, end_date, include_info=True):
        """
        Collect all data for a single ticker
        
        Args:
            ticker: Stock ticker symbol
            start_date: Start date
            end_date: End date
            include_info: Whether to fetch company info
        
        Returns:
            Dictionary with status and data
        """
        try:
            # Fetch prices
            prices_df = self.fetch_historical_prices(ticker, start_date, end_date)
            self.save_prices(prices_df, ticker)
            
            # Fetch company info if requested
            if include_info:
                info = self.fetch_company_info(ticker)
                self.save_company_info(info, ticker)
            
            return {
                'ticker': ticker,
                'status': 'success',
                'records': len(prices_df),
                'start_date': prices_df['date'].min().strftime('%Y-%m-%d'),
                'end_date': prices_df['date'].max().strftime('%Y-%m-%d')
            }
            
        except Exception as e:
            logger.error(f"Failed to collect data for {ticker}: {str(e)}")
            return {
                'ticker': ticker,
                'status': 'failed',
                'error': str(e)
            }
    
    def collect_for_multiple_tickers(self, tickers, start_date, end_date, include_info=True):
        """
        Collect data for multiple tickers
        
        Args:
            tickers: List of ticker symbols
            start_date: Start date
            end_date: End date
            include_info: Whether to fetch company info
        
        Returns:
            List of results for each ticker
        """
        results = []
        
        for ticker in tickers:
            logger.info(f"Processing {ticker} ({tickers.index(ticker)+1}/{len(tickers)})")
            result = self.collect_for_ticker(ticker, start_date, end_date, include_info)
            results.append(result)
        
        # Summary
        successful = sum(1 for r in results if r['status'] == 'success')
        logger.info(f"Completed: {successful}/{len(tickers)} tickers successful")
        
        return results


def main():
    """Example usage"""
    collector = StockPriceCollector()
    
    # Test with single ticker
    tickers = ['AAPL', 'MSFT', 'GOOGL']
    start_date = '2023-01-01'
    end_date = '2025-11-01'
    
    results = collector.collect_for_multiple_tickers(tickers, start_date, end_date)
    
    # Print summary
    for result in results:
        print(f"{result['ticker']}: {result['status']}")
        if result['status'] == 'success':
            print(f"  Records: {result['records']}")
            print(f"  Date range: {result['start_date']} to {result['end_date']}")


if __name__ == '__main__':
    main()