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
                # Wait until enough calls expire to give us breathing room
                # Clear at least 25% of the limit or 10 calls, whichever is smaller
                calls_to_clear = min(max(1, self.max_calls // 4), 10)
                
                # Find when the Nth oldest call expires
                if len(self.calls) >= calls_to_clear:
                    target_call = self.calls[calls_to_clear - 1]
                else:
                    target_call = self.calls[0]
                
                sleep_time = (target_call + timedelta(seconds=self.period) - now).total_seconds() + 0.3  # +0.1s buffer
                
                if sleep_time > 0:
                    print(f"Rate limit reached. Sleeping for {sleep_time:.2f} seconds to clear {calls_to_clear} slots...")
                    time.sleep(sleep_time)
                    
                    # Clean up expired calls after sleeping
                    now = datetime.now()
                    while self.calls and self.calls[0] < now - timedelta(seconds=self.period):
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
finnhub_limiter = RateLimiter(max_calls=54, period=60)  # 54 instead of 60
alpha_vantage_limiter = RateLimiter(max_calls=4, period=60)  # 4 instead of 5
reddit_limiter = RateLimiter(max_calls=54, period=60)  # 54 instead of 60
sec_limiter = simple_rate_limit(calls_per_second=9)  # 9 instead of 10
yfinance_limiter = simple_rate_limit(calls_per_second=0.5)  # ~1800/hr instead of 2000

#print("Rate limiters initialized for APIs")