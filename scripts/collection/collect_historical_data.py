"""
Master script to collect all historical data
Run this once to gather data for your analysis period
"""
import sys
from pathlib import Path
import json
from datetime import datetime

# Add parent directory to path
sys.path.append(str(Path(__file__).parent))

from collection.stock_prices import StockPriceCollector
from collection.earnings import EarningsCollector
from utils.error_handler import create_logger

logger = create_logger(__name__)


class HistoricalDataCollector:
    """Master collector for all data sources"""
    
    def __init__(self, tickers, start_date, end_date):
        self.tickers = tickers
        self.start_date = start_date
        self.end_date = end_date
        
        # Initialize collectors
        self.price_collector = StockPriceCollector()
        self.earnings_collector = EarningsCollector()
        
        logger.info(f"Initialized collectors for {len(tickers)} tickers")
        logger.info(f"Date range: {start_date} to {end_date}")
    
    def collect_all(self, skip_prices=False, skip_earnings=False):
        """
        Run all data collection
        
        Args:
            skip_prices: Skip price collection (if already done)
            skip_earnings: Skip earnings collection (if already done)
        
        Returns:
            Dictionary with results summary
        """
        results = {
            'tickers': self.tickers,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'timestamp': datetime.now().isoformat(),
            'collections': {}
        }
        
        # 1. Collect stock prices
        if not skip_prices:
            logger.info("\n" + "="*50)
            logger.info("STEP 1: Collecting Stock Prices")
            logger.info("="*50)
            
            price_results = self.price_collector.collect_for_multiple_tickers(
                self.tickers, 
                self.start_date, 
                self.end_date
            )
            results['collections']['prices'] = price_results
        else:
            logger.info("Skipping price collection")
        
        # 2. Collect earnings data
        if not skip_earnings:
            logger.info("\n" + "="*50)
            logger.info("STEP 2: Collecting Earnings Data")
            logger.info(f"WARNING: This will use {len(self.tickers)} API calls")
            logger.info("="*50)
            
            # Confirm before proceeding
            print(f"\nAbout to use {len(self.tickers)} of your 25 daily Alpha Vantage calls")
            print("Continue? (yes/no): ", end='')
            response = input()
            
            if response.lower() == 'yes':
                earnings_results = self.earnings_collector.collect_for_multiple_tickers(
                    self.tickers
                )
                results['collections']['earnings'] = earnings_results
            else:
                logger.info("Skipping earnings collection")
                results['collections']['earnings'] = {'status': 'skipped'}
        else:
            logger.info("Skipping earnings collection")
        
        # 3. TODO: Add SEC filings collector
        logger.info("\n" + "="*50)
        logger.info("STEP 3: SEC Filings (Not implemented yet)")
        logger.info("="*50)
        
        # 4. TODO: Add Reddit collector
        logger.info("\n" + "="*50)
        logger.info("STEP 4: Reddit Sentiment (Not implemented yet)")
        logger.info("="*50)
        
        # 5. TODO: Add news collector
        logger.info("\n" + "="*50)
        logger.info("STEP 5: News Data (Not implemented yet)")
        logger.info("="*50)
        
        return results
    
    def save_collection_report(self, results):
        """Save collection summary report"""
        output_dir = Path('data/reports')
        output_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = output_dir / f'collection_report_{timestamp}.json'
        
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        logger.info(f"\nCollection report saved to {output_file}")
        
        # Print summary
        self.print_summary(results)
    
    def print_summary(self, results):
        """Print human-readable summary"""
        print("\n" + "="*70)
        print("COLLECTION SUMMARY")
        print("="*70)
        
        print(f"\nTickers: {', '.join(results['tickers'])}")
        print(f"Date Range: {results['start_date']} to {results['end_date']}")
        print(f"Completed: {results['timestamp']}")
        
        # Prices summary
        if 'prices' in results['collections']:
            prices = results['collections']['prices']
            successful = sum(1 for r in prices if r['status'] == 'success')
            print(f"\nStock Prices: {successful}/{len(prices)} successful")
        
        # Earnings summary
        if 'earnings' in results['collections']:
            earnings = results['collections']['earnings']
            if isinstance(earnings, dict) and earnings.get('status') == 'skipped':
                print(f"\nEarnings: Skipped")
            else:
                successful = sum(1 for r in earnings if r['status'] == 'success')
                print(f"\nEarnings: {successful}/{len(earnings)} successful")
        
        print("\n" + "="*70)


def main():
    """
    Main execution
    
    Customize these parameters for your project
    """
    
    # CONFIGURATION (customize as needed)
    TICKERS = [
        'AAPL',  # Apple
        'MSFT',  # Microsoft
        'GOOGL', # Alphabet
        'AMZN',  # Amazon
        'TSLA',  # Tesla
        'META',  # Meta
        'NVDA',  # Nvidia
        'JPM',   # JP Morgan
        'V',     # Visa
        'WMT',   # Walmart
        'DIS',   # Disney
        'NFLX',  # Netflix
        'BA',    # Boeing
        'GE',    # General Electric
        'F'      # Ford
    ]
    
    START_DATE = '2023-01-01'
    END_DATE = '2024-11-01'
    
    # Initialize collector
    collector = HistoricalDataCollector(TICKERS, START_DATE, END_DATE)
    
    # Run collection
    print("\n" + "="*70)
    print("HISTORICAL DATA COLLECTION")
    print("="*70)
    print(f"\nThis will collect data for {len(TICKERS)} stocks")
    print(f"From {START_DATE} to {END_DATE}")
    print("\nData to collect:")
    print("  1. Stock prices (yfinance) - FREE")
    print(f"  2. Earnings data (Alpha Vantage) - Uses {len(TICKERS)} of 25 daily calls")
    print("  3. SEC filings (coming next)")
    print("  4. Reddit sentiment (coming next)")
    print("  5. News data (coming next)")
    print("\nReady to begin? (yes/no): ", end='')
    
    response = input()
    
    if response.lower() != 'yes':
        print("Collection cancelled")
        return
    
    # Run collection
    results = collector.collect_all()
    
    # Save report
    collector.save_collection_report(results)
    
    print("\nCollection complete!")
    print("Next steps:")
    print("  1. Check data/raw/ directories for collected data")
    print("  2. Review the collection report")
    print("  3. Build remaining collectors (SEC, Reddit, News)")


if __name__ == '__main__':
    main()