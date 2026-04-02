"""Exception handling utilities for AlphaKRX."""

import logging
from functools import wraps
from typing import Any, Callable, Optional, TypeVar

T = TypeVar("T")


def safe_execute(
    default: Any = None,
    log_errors: bool = True,
    error_message: str = "Operation failed",
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator that catches exceptions and returns a default value.
    
    Args:
        default: Value to return on exception
        log_errors: Whether to log the exception
        error_message: Custom error message to log
        
    Returns:
        Decorated function
        
    Example:
        @safe_execute(default=[], log_errors=True)
        def get_data():
            return fetch_data()
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if log_errors:
                    logging.getLogger(func.__module__).warning(
                        f"{error_message}: {type(e).__name__}: {e}"
                    )
                return default
        return wrapper
    return decorator


class AlphaKRXError(Exception):
    """Base exception for AlphaKRX."""
    pass


class DataNotFoundError(AlphaKRXError):
    """Raised when required data is not found."""
    pass


class ConfigurationError(AlphaKRXError):
    """Raised when configuration is invalid."""
    pass


class ModelError(AlphaKRXError):
    """Raised when model operations fail."""
    pass


class APIError(AlphaKRXError):
    """Raised when API calls fail."""
    pass


class DatabaseError(AlphaKRXError):
    """Raised when database operations fail."""
    pass


def reraise_as(
    target_exception: type[Exception],
    message: Optional[str] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that reraises exceptions as a different type.
    
    Args:
        target_exception: Exception type to raise
        message: Optional custom message
        
    Returns:
        Decorated function
        
    Example:
        @reraise_as(DataNotFoundError, "Failed to load data")
        def load_data():
            return fetch_data()
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                msg = message or f"{type(e).__name__}: {e}"
                raise target_exception(msg) from e
        return wrapper
    return decorator
