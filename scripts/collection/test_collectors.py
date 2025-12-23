"""
Test script to verify all collectors are working
Run this before doing full historical collection
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from collection.stock_prices import StockPriceCollector
from collection.earnings import EarningsCollector
from utils.error_handler import create_logger

logger = create_logger(__name__)


def test_price_collector():
    """Test stock price collector with single ticker"""
    print("\n" + "="*50)
    print("Testing Stock Price Collector")
    print("="*50)
    
    try:
        collector = StockPriceCollector(output_dir='data/test/prices')
        
        # Test with just AAPL for 1 month
        result = collector.collect_for_ticker(
            ticker='AAPL',
            start_date='2024-10-01',
            end_date='2024-11-01',
            include_info=True
        )
        
        if result['status'] == 'success':
            print("Price collector working!")
            print(f"   Collected {result['records']} days of data")
            return True
        else:
            print("Price collector failed")
            print(f"   Error: {result.get('error', 'Unknown')}")
            return False
            
    except Exception as e:
        print(f"Price collector error: {str(e)}")
        return False


def test_earnings_collector():
    """Test earnings collector with single ticker"""
    print("\n" + "="*50)
    print("Testing Earnings Collector")
    print("="*50)
    print("This will use 1 of your 25 daily API calls")
    print("Continue? (yes/no): ", end='')
    
    response = input()
    if response.lower() != 'yes':
        print("Skipped earnings collector test")
        return None
    
    try:
        collector = EarningsCollector(output_dir='data/test/earnings')
        
        # Test with just AAPL
        result = collector.collect_for_ticker(ticker='AAPL')
        
        if result['status'] == 'success':
            print("Earnings collector working!")
            print(f"   Collected {result['records']} earnings reports")
            print(f"   Date range: {result['date_range']}")
            return True
        elif result['status'] == 'no_data':
            print("No earnings data found (but collector works)")
            return True
        else:
            print("Earnings collector failed")
            print(f"   Error: {result.get('error', 'Unknown')}")
            return False
            
    except Exception as e:
        print(f"Earnings collector error: {str(e)}")
        return False


def test_rate_limiters():
    """Test that rate limiters are working"""
    print("\n" + "="*50)
    print("Testing Rate Limiters")
    print("="*50)
    
    from utils.rate_limiter import simple_rate_limit
    import time
    
    @simple_rate_limit(calls_per_second=2)
    def dummy_call(n):
        return n
    
    try:
        start = time.time()
        
        # Make 5 calls (should take ~2 seconds with rate limit)
        for i in range(5):
            dummy_call(i)
        
        elapsed = time.time() - start
        
        if elapsed >= 2.0:
            print(f"Rate limiter working! (took {elapsed:.2f}s for 5 calls)")
            return True
        else:
            print(f"Rate limiter might not be working (took only {elapsed:.2f}s)")
            return False
            
    except Exception as e:
        print(f"Rate limiter error: {str(e)}")
        return False


def test_error_handlers():
    """Test error handling and retry logic"""
    print("\n" + "="*50)
    print("Testing Error Handlers")
    print("="*50)
    
    from utils.error_handler import retry_on_failure
    
    # Test retry logic with a function that fails twice then succeeds
    attempt_count = [0]
    
    @retry_on_failure(max_retries=3, backoff_factor=0.1)
    def flaky_function():
        attempt_count[0] += 1
        if attempt_count[0] < 3:
            raise Exception(f"Attempt {attempt_count[0]} failed")
        return "Success!"
    
    try:
        result = flaky_function()
        if result == "Success!" and attempt_count[0] == 3:
            print("Error handler and retry logic working!")
            return True
        else:
            print("Error handler working but unexpected behavior")
            return False
            
    except Exception as e:
        print(f"Error handler test failed: {str(e)}")
        return False


def main():
    """Run all tests"""
    print("\n" + "="*70)
    print("TESTING DATA COLLECTION INFRASTRUCTURE")
    print("="*70)
    
    results = {}
    
    # Test each component
    results['rate_limiters'] = test_rate_limiters()
    results['error_handlers'] = test_error_handlers()
    results['price_collector'] = test_price_collector()
    results['earnings_collector'] = test_earnings_collector()
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    for test_name, passed in results.items():
        if passed is True:
            status = "PASS"
        elif passed is False:
            status = "FAIL"
        else:
            status = "SKIP"
        print(f"{test_name:20s}: {status}")
    
    # Overall status
    failed_tests = [name for name, passed in results.items() if passed is False]
    
    if failed_tests:
        print(f"\n{len(failed_tests)} test(s) failed: {', '.join(failed_tests)}")
        print("Fix these issues before running full collection")
    else:
        print("\nAll tests passed!")
        print("Ready to run full historical data collection")
        print("\nNext step: python scripts/collect_historical_data.py")


if __name__ == '__main__':
    main()