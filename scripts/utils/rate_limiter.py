"""
Rate limiting utilities for API calls
"""
import time
import functools
from collections import deque
from datetime import datetime, timedelta


class RateLimiter:
    """
    Rate limiter that tracks API calls and enforces limits
    
    Usage:
        limiter = RateLimiter(max_calls=60, period=60)  # 60 calls per minute
        
        @limiter
        def api_call():
            return requests.get(...)
    """
    
    def __init__(self, max_calls, period):
        """
        Args:
            max_calls: Maximum number of calls allowed
            period: Time period in seconds
        """
        self.max_calls = max_calls
        self.period = period
        self.calls = deque()
    
    def __call__(self, func):
        """Decorator to rate limit function calls"""
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            now = datetime.now()
            
            # Remove calls outside the time window
            while self.calls and self.calls[0] < now - timedelta(seconds=self.period):
                self.calls.popleft()
            
            # Check if we're at the limit
            if len(self.calls) >= self.max_calls:
                sleep_time = (self.calls[0] + timedelta(seconds=self.period) - now).total_seconds()
                if sleep_time > 0:
                    print(f"Rate limit reached. Sleeping for {sleep_time:.2f} seconds...")
                    time.sleep(sleep_time)
                    # Remove old calls after sleeping
                    while self.calls and self.calls[0] < datetime.now() - timedelta(seconds=self.period):
                        self.calls.popleft()
            
            # Record this call
            self.calls.append(datetime.now())
            
            # Make the actual call
            return func(*args, **kwargs)
        
        return wrapper


def simple_rate_limit(calls_per_second=1):
    """
    Simple rate limiter - just adds delay between calls
    
    Usage:
        @simple_rate_limit(calls_per_second=2)
        def api_call():
            return requests.get(...)
    """
    def decorator(func):
        last_called = [0.0]
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            elapsed = time.time() - last_called[0]
            left_to_wait = (1.0 / calls_per_second) - elapsed
            
            if left_to_wait > 0:
                time.sleep(left_to_wait)
            
            ret = func(*args, **kwargs)
            last_called[0] = time.time()
            return ret
        
        return wrapper
    return decorator


# Pre-configured rate limiters for each API
alpha_vantage_limiter = RateLimiter(max_calls=5, period=60)  # 5 per minute
reddit_limiter = RateLimiter(max_calls=60, period=60)  # 60 per minute
sec_limiter = simple_rate_limit(calls_per_second=10)  # 10 per second
finnhub_limiter = RateLimiter(max_calls=60, period=60)  # 60 per minute
yfinance_limiter = simple_rate_limit(calls_per_second=2000/3600)  # ~2000 per hour

#print("Rate limiters initialized for APIs")