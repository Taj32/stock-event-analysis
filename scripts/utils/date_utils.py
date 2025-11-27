"""
Date utility functions for data collection
"""
from datetime import datetime, timedelta
import pandas as pd


def get_trading_days(start_date, end_date):
    """
    Get list of trading days between two dates (excludes weekends)
    
    Args:
        start_date: Start date (string 'YYYY-MM-DD' or datetime)
        end_date: End date (string 'YYYY-MM-DD' or datetime)
    
    Returns:
        List of datetime objects for trading days
    """
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, '%Y-%m-%d')
    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, '%Y-%m-%d')
    
    # Generate all days
    date_range = pd.date_range(start=start_date, end=end_date, freq='B')  # B = business days
    return date_range.tolist()


def get_date_range(start_date, end_date):
    """
    Get all dates between start and end (including weekends)
    
    Args:
        start_date: Start date (string 'YYYY-MM-DD' or datetime)
        end_date: End date (string 'YYYY-MM-DD' or datetime)
    
    Returns:
        List of datetime objects
    """
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, '%Y-%m-%d')
    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, '%Y-%m-%d')
    
    dates = []
    current = start_date
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=1)
    
    return dates


def format_date(date, format='%Y-%m-%d'):
    """
    Format date to string
    
    Args:
        date: datetime object or string
        format: Output format
    
    Returns:
        Formatted date string
    """
    if isinstance(date, str):
        date = datetime.strptime(date, '%Y-%m-%d')
    return date.strftime(format)


def parse_date(date_string, format='%Y-%m-%d'):
    """
    Parse date string to datetime
    
    Args:
        date_string: Date as string
        format: Input format
    
    Returns:
        datetime object
    """
    return datetime.strptime(date_string, format)


def get_window_dates(event_date, days_before=30, days_after=30):
    """
    Get date window around an event
    
    Args:
        event_date: Event date (string or datetime)
        days_before: Days before event
        days_after: Days after event
    
    Returns:
        Tuple of (start_date, end_date) as datetime objects
    """
    if isinstance(event_date, str):
        event_date = datetime.strptime(event_date, '%Y-%m-%d')
    
    start_date = event_date - timedelta(days=days_before)
    end_date = event_date + timedelta(days=days_after)
    
    return start_date, end_date


def is_market_open(date):
    """
    Check if market is likely open on given date (basic check - excludes weekends)
    
    Note: This doesn't account for holidays, just weekends
    
    Args:
        date: datetime object
    
    Returns:
        Boolean
    """
    return date.weekday() < 5  # Monday = 0, Friday = 4


def get_last_trading_day(date=None):
    """
    Get the last trading day (excluding weekends)
    
    Args:
        date: Reference date (default: today)
    
    Returns:
        datetime object of last trading day
    """
    if date is None:
        date = datetime.now()
    
    # Go back to find last weekday
    while date.weekday() >= 5:  # Saturday or Sunday
        date -= timedelta(days=1)
    
    return date


def chunk_date_range(start_date, end_date, chunk_size_days=30):
    """
    Split date range into chunks (useful for APIs with limits)
    
    Args:
        start_date: Start date
        end_date: End date
        chunk_size_days: Size of each chunk in days
    
    Returns:
        List of (start, end) tuples
    """
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, '%Y-%m-%d')
    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, '%Y-%m-%d')
    
    chunks = []
    current_start = start_date
    
    while current_start < end_date:
        current_end = min(current_start + timedelta(days=chunk_size_days), end_date)
        chunks.append((current_start, current_end))
        current_start = current_end + timedelta(days=1)
    
    return chunks