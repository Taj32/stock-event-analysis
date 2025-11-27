"""
Error handling and retry logic for API calls
"""
import time
import functools
import logging
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/data_collection.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


def retry_on_failure(max_retries=3, backoff_factor=2, exceptions=(Exception,)):
    """
    Retry decorator with exponential backoff
    
    Args:
        max_retries: Maximum number of retry attempts
        backoff_factor: Multiplier for wait time between retries
        exceptions: Tuple of exceptions to catch and retry
    
    Usage:
        @retry_on_failure(max_retries=3, backoff_factor=2)
        def api_call():
            return requests.get(...)
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                    
                except exceptions as e:
                    last_exception = e
                    
                    if attempt < max_retries:
                        wait_time = backoff_factor ** attempt
                        logger.warning(
                            f"{func.__name__} failed (attempt {attempt + 1}/{max_retries + 1}): {str(e)}. "
                            f"Retrying in {wait_time} seconds..."
                        )
                        time.sleep(wait_time)
                    else:
                        logger.error(
                            f"{func.__name__} failed after {max_retries + 1} attempts: {str(e)}"
                        )
            
            # If we get here, all retries failed
            raise last_exception
        
        return wrapper
    return decorator


def log_api_call(func):
    """
    Decorator to log API calls
    
    Usage:
        @log_api_call
        def get_data():
            return requests.get(...)
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        logger.info(f"Starting {func.__name__} with args={args[:2]}, kwargs={list(kwargs.keys())}")
        
        try:
            result = func(*args, **kwargs)
            elapsed = time.time() - start_time
            logger.info(f"{func.__name__} completed successfully in {elapsed:.2f}s")
            return result
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"{func.__name__} failed after {elapsed:.2f}s: {str(e)}")
            raise
    
    return wrapper


def safe_api_call(func):
    """
    Wrapper that combines logging and retry logic
    Good for most API calls
    
    Usage:
        @safe_api_call
        def get_data():
            return requests.get(...)
    """
    return log_api_call(retry_on_failure(max_retries=3)(func))


class APIError(Exception):
    """Custom exception for API errors"""
    pass


class RateLimitError(APIError):
    """Raised when rate limit is exceeded"""
    pass


class DataNotFoundError(APIError):
    """Raised when requested data doesn't exist"""
    pass


def handle_response(response, api_name="API"):
    """
    Standard response handler for requests
    
    Args:
        response: requests.Response object
        api_name: Name of the API for error messages
    
    Returns:
        JSON data from response
    
    Raises:
        RateLimitError: If rate limit exceeded
        DataNotFoundError: If resource not found
        APIError: For other API errors
    """
    if response.status_code == 200:
        return response.json()
    
    elif response.status_code == 429:
        retry_after = response.headers.get('Retry-After', 60)
        logger.warning(f"{api_name} rate limit exceeded. Retry after {retry_after}s")
        raise RateLimitError(f"Rate limit exceeded. Retry after {retry_after}s")
    
    elif response.status_code == 404:
        logger.warning(f"{api_name} resource not found: {response.url}")
        raise DataNotFoundError(f"Resource not found: {response.url}")
    
    elif response.status_code >= 500:
        logger.error(f"{api_name} server error: {response.status_code}")
        raise APIError(f"Server error: {response.status_code}")
    
    else:
        logger.error(f"{api_name} error {response.status_code}: {response.text}")
        raise APIError(f"API error {response.status_code}: {response.text}")


def create_logger(name):
    """Create a logger for a specific module"""
    return logging.getLogger(name)