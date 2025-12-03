"""
SEC Filing collector using SEC EDGAR API
"""
import requests
import json
import time
from pathlib import Path
from datetime import datetime
import pandas as pd
import sys
sys.path.append(str(Path(__file__).parent.parent))

from utils.rate_limiter import sec_limiter
from utils.error_handler import safe_api_call, create_logger, handle_response
from utils.date_utils import format_date

logger = create_logger(__name__)


class SECFilingCollector:
    """Collector for SEC filings from EDGAR"""
    
    def __init__(self, user_agent, output_dir='data/raw/sec_filings'):
        """
        Args:
            user_agent: Your contact info (REQUIRED by SEC)
                       Format: "YourName your@email.com"
        """
        if not user_agent or '@' not in user_agent:
            raise ValueError(
                "SEC requires valid User-Agent with contact info.\n"
                "Format: 'YourName your@email.com'"
            )
        
        self.user_agent = user_agent
        self.headers = {
            'User-Agent': user_agent,
            'Accept-Encoding': 'gzip, deflate',
            'Host': 'data.sec.gov'
        }
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Load ticker to CIK mapping
        self.ticker_to_cik = {}
        self._load_ticker_cik_mapping()
    
    def _load_ticker_cik_mapping(self):
        """Load SEC's ticker to CIK mapping"""
        logger.info("Loading ticker to CIK mapping...")
        
        try:
            url = "https://www.sec.gov/files/company_tickers.json"
            response = requests.get(url, headers=self.headers)
            
            if response.status_code == 200:
                data = response.json()
                
                # Convert to ticker: CIK mapping
                for item in data.values():
                    ticker = item['ticker'].upper()
                    cik = str(item['cik_str']).zfill(10)  # Pad to 10 digits
                    self.ticker_to_cik[ticker] = cik
                
                logger.info(f"Loaded {len(self.ticker_to_cik)} ticker-CIK mappings")
            else:
                logger.warning("Could not load ticker-CIK mapping from SEC")
                
        except Exception as e:
            logger.error(f"Error loading ticker-CIK mapping: {e}")
    
    def get_cik(self, ticker):
        """
        Get CIK for a ticker
        
        Args:
            ticker: Stock ticker symbol
        
        Returns:
            CIK string (10 digits) or None
        """
        cik = self.ticker_to_cik.get(ticker.upper())
        if not cik:
            logger.warning(f"CIK not found for {ticker}")
        return cik
    
    @sec_limiter
    @safe_api_call
    def fetch_company_submissions(self, ticker):
        """
        Fetch all submission data for a company
        
        Args:
            ticker: Stock ticker symbol
        
        Returns:
            Dictionary with all filings metadata
        """
        cik = self.get_cik(ticker)
        if not cik:
            raise ValueError(f"Could not find CIK for ticker {ticker}")
        
        logger.info(f"Fetching submissions for {ticker} (CIK: {cik})")
        
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        response = requests.get(url, headers=self.headers)
        
        if response.status_code == 200:
            data = response.json()
            logger.info(f"Successfully fetched submissions for {ticker}")
            return data
        else:
            logger.error(f"Failed to fetch {ticker}: {response.status_code}")
            raise Exception(f"SEC API error: {response.status_code}")
    
    def parse_filings(self, submissions_data, ticker, form_types=['8-K'], 
                     start_date=None, end_date=None):
        """
        Parse filings from submissions data
        
        Args:
            submissions_data: Raw SEC submissions data
            ticker: Stock ticker
            form_types: List of form types to include (e.g., ['8-K', '10-Q'])
            start_date: Start date filter (YYYY-MM-DD)
            end_date: End date filter (YYYY-MM-DD)
        
        Returns:
            DataFrame with filtered filings
        """
        recent_filings = submissions_data.get('filings', {}).get('recent', {})
        
        if not recent_filings:
            logger.warning(f"No recent filings found for {ticker}")
            return pd.DataFrame()
        
        # Convert to DataFrame
        df = pd.DataFrame({
            'accessionNumber': recent_filings.get('accessionNumber', []),
            'filingDate': recent_filings.get('filingDate', []),
            'reportDate': recent_filings.get('reportDate', []),
            'acceptanceDateTime': recent_filings.get('acceptanceDateTime', []),
            'form': recent_filings.get('form', []),
            'primaryDocument': recent_filings.get('primaryDocument', []),
            'primaryDocDescription': recent_filings.get('primaryDocDescription', [])
        })
        
        if df.empty:
            return df
        
        # Add ticker
        df['ticker'] = ticker
        
        # Convert dates
        df['filingDate'] = pd.to_datetime(df['filingDate'])
        df['reportDate'] = pd.to_datetime(df['reportDate'])
        
        # Filter by form type
        if form_types:
            df = df[df['form'].isin(form_types)]
        
        # Filter by date range
        if start_date:
            df = df[df['filingDate'] >= pd.to_datetime(start_date)]
        if end_date:
            df = df[df['filingDate'] <= pd.to_datetime(end_date)]
        
        # Sort by date (most recent first)
        df = df.sort_values('filingDate', ascending=False)
        
        logger.info(f"Found {len(df)} {form_types} filings for {ticker}")
        
        return df
    
    def parse_8k_items(self, filing_description):
        """
        Extract Item numbers from 8-K filing description
        
        Args:
            filing_description: Description text from filing
        
        Returns:
            List of item numbers (e.g., ['2.02', '9.01'])
        """
        items = []
        
        # Common 8-K items to look for
        item_patterns = {
            '1.01': 'Entry into a Material Definitive Agreement',
            '1.02': 'Termination of a Material Definitive Agreement',
            '2.02': 'Results of Operations and Financial Condition',
            '2.03': 'Creation of a Direct Financial Obligation',
            '5.02': 'Departure of Directors or Certain Officers',
            '5.03': 'Amendments to Articles of Incorporation or Bylaws',
            '7.01': 'Regulation FD Disclosure',
            '8.01': 'Other Events',
            '9.01': 'Financial Statements and Exhibits'
        }
        
        if not filing_description:
            return items
        
        desc_lower = filing_description.lower()
        
        for item_num, item_desc in item_patterns.items():
            # Check for item number
            if f'item {item_num}' in desc_lower or f'{item_num}' in desc_lower:
                items.append(item_num)
            # Check for description keywords
            elif any(keyword in desc_lower for keyword in item_desc.lower().split()[:3]):
                items.append(item_num)
        
        return items
    
    def categorize_8k(self, items):
        """
        Categorize 8-K filing based on items
        
        Args:
            items: List of item numbers
        
        Returns:
            Category string
        """
        if not items:
            return 'Other'
        
        # Priority order for categorization
        if '2.02' in items:
            return 'Earnings Announcement'
        elif '5.02' in items:
            return 'Management Change'
        elif '1.01' in items:
            return 'Material Agreement'
        elif '8.01' in items:
            return 'Other Material Event'
        else:
            return 'Other'
    
    def build_filing_url(self, accession_number, primary_document):
        """
        Build URL to access filing
        
        Args:
            accession_number: SEC accession number
            primary_document: Primary document filename
        
        Returns:
            URL string
        """
        # Remove dashes from accession number for URL
        acc_no_dashes = accession_number.replace('-', '')
        
        return f"https://www.sec.gov/Archives/edgar/data/{acc_no_dashes}/{accession_number}/{primary_document}"
    
    def save_filings_list(self, df, ticker):
        """
        Save filings list to CSV
        
        Args:
            df: DataFrame with filings
            ticker: Stock ticker
        """
        output_file = self.output_dir / f"{ticker}_filings.csv"
        df.to_csv(output_file, index=False)
        logger.info(f"Saved {len(df)} filings to {output_file}")
    
    def save_raw_response(self, data, ticker):
        """
        Save raw SEC response to JSON
        
        Args:
            data: Raw SEC data
            ticker: Stock ticker
        """
        output_file = self.output_dir / f"{ticker}_submissions_raw.json"
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved raw submissions data to {output_file}")
    
    def collect_for_ticker(self, ticker, form_types=['8-K'], 
                          start_date=None, end_date=None, save_raw=True):
        """
        Collect SEC filings for a ticker
        
        Args:
            ticker: Stock ticker
            form_types: List of form types to collect
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            save_raw: Whether to save raw API response
        
        Returns:
            Dictionary with status and data
        """
        try:
            # Fetch submissions
            submissions = self.fetch_company_submissions(ticker)
            
            # Save raw data if requested
            if save_raw:
                self.save_raw_response(submissions, ticker)
            
            # Parse filings
            df = self.parse_filings(
                submissions, 
                ticker, 
                form_types=form_types,
                start_date=start_date,
                end_date=end_date
            )
            
            if df.empty:
                return {
                    'ticker': ticker,
                    'status': 'no_data',
                    'records': 0
                }
            
            # For 8-Ks, parse items and categorize
            if '8-K' in form_types:
                df['items'] = df['primaryDocDescription'].apply(self.parse_8k_items)
                df['items_str'] = df['items'].apply(lambda x: ','.join(x) if x else '')
                df['category'] = df['items'].apply(self.categorize_8k)
            
            # Build filing URLs
            df['filing_url'] = df.apply(
                lambda row: self.build_filing_url(row['accessionNumber'], row['primaryDocument']),
                axis=1
            )
            
            # Save to CSV
            self.save_filings_list(df, ticker)
            
            return {
                'ticker': ticker,
                'status': 'success',
                'records': len(df),
                'date_range': {
                    'earliest': df['filingDate'].min().strftime('%Y-%m-%d'),
                    'latest': df['filingDate'].max().strftime('%Y-%m-%d')
                },
                'form_types': df['form'].value_counts().to_dict()
            }
            
        except Exception as e:
            logger.error(f"Failed to collect SEC filings for {ticker}: {str(e)}")
            return {
                'ticker': ticker,
                'status': 'failed',
                'error': str(e)
            }
    
    def collect_for_multiple_tickers(self, tickers, form_types=['8-K'],
                                    start_date=None, end_date=None):
        """
        Collect SEC filings for multiple tickers
        
        Args:
            tickers: List of ticker symbols
            form_types: List of form types to collect
            start_date: Start date
            end_date: End date
        
        Returns:
            List of results for each ticker
        """
        results = []
        
        for i, ticker in enumerate(tickers, 1):
            logger.info(f"Processing {ticker} ({i}/{len(tickers)})")
            
            result = self.collect_for_ticker(
                ticker,
                form_types=form_types,
                start_date=start_date,
                end_date=end_date
            )
            results.append(result)
            
            # Progress update
            if i % 5 == 0:
                successful = sum(1 for r in results if r['status'] == 'success')
                logger.info(f"Progress: {i}/{len(tickers)}, {successful} successful")
        
        # Final summary
        successful = sum(1 for r in results if r['status'] == 'success')
        failed = sum(1 for r in results if r['status'] == 'failed')
        no_data = sum(1 for r in results if r['status'] == 'no_data')
        
        logger.info(f"Completed: {successful} success, {failed} failed, {no_data} no data")
        
        return results


def main():
    """Example usage"""
    
    # IMPORTANT: Replace with YOUR contact info
    user_agent = "temp temp@example.com"  # CHANGE THIS!
    
    collector = SECFilingCollector(user_agent=user_agent)
    
    # Test with small batch
    tickers = ['AAPL', 'MSFT', 'GOOGL']
    start_date = '2023-01-01'
    end_date = '2024-11-01'
    
    print(f"\nCollecting 8-K filings for {len(tickers)} stocks")
    print(f"Date range: {start_date} to {end_date}")
    print("This is FREE (no API limits)\n")
    
    results = collector.collect_for_multiple_tickers(
        tickers,
        form_types=['8-K'],  # Can add '10-Q', '10-K', etc.
        start_date=start_date,
        end_date=end_date
    )
    
    # Print summary
    for result in results:
        print(f"\n{result['ticker']}: {result['status']}")
        if result['status'] == 'success':
            print(f"  Total filings: {result['records']}")
            print(f"  Date range: {result['date_range']}")
            print(f"  Form types: {result['form_types']}")


if __name__ == '__main__':
    main()