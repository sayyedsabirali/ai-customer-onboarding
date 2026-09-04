import time
import random
import functools
import inspect
import asyncio
from typing import Callable, Any, Optional, List, Dict
import requests

from utils.logger import get_logger

logger = get_logger("resilience")


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 0.5,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    jitter_factor: float = 0.25,
    exceptions: tuple = (requests.RequestException, TimeoutError, ConnectionError),
    on_retry: Optional[Callable[[int, float, Exception], None]] = None
):
    """
    Decorator for retrying functions with exponential backoff and jitter.
    Supports both synchronous and asynchronous functions.
    Attaches `retry_history` list to the wrapper function for observability and verification.
    """
    def decorator(func: Callable) -> Callable:
        is_async = asyncio.iscoroutinefunction(func)

        if is_async:
            @functools.wraps(func)
            async def wrapper(*args, **kwargs) -> Any:
                wrapper.retry_history = []
                delay = initial_delay
                last_exception = None

                for attempt in range(1, max_retries + 1):
                    try:
                        return await func(*args, **kwargs)
                    except exceptions as e:
                        last_exception = e
                        if attempt == max_retries:
                            logger.error(
                                f"Async call to {func.__name__} failed after {max_retries} attempts: {str(e)}",
                                extra={"action": "retry_exhausted", "error": str(e), "attempts": max_retries}
                            )
                            raise

                        jitter_amount = random.uniform(0.01, delay * jitter_factor) if jitter else 0.0
                        sleep_time = delay + jitter_amount

                        retry_info = {
                            "attempt": attempt,
                            "base_delay": round(delay, 4),
                            "jitter": round(jitter_amount, 4),
                            "sleep_time": round(sleep_time, 4),
                            "error": str(e)
                        }
                        wrapper.retry_history.append(retry_info)

                        if on_retry:
                            on_retry(attempt, sleep_time, e)

                        logger.warning(
                            f"Transient error in {func.__name__} (attempt {attempt}/{max_retries}): {str(e)}. Retrying in {sleep_time:.3f}s (base: {delay}s, jitter: +{jitter_amount:.3f}s)...",
                            extra={"action": "retry_attempt", "attempt": attempt, "delay": round(sleep_time, 3)}
                        )
                        await asyncio.sleep(sleep_time)
                        delay *= backoff_factor

                raise last_exception
        else:
            @functools.wraps(func)
            def wrapper(*args, **kwargs) -> Any:
                wrapper.retry_history = []
                delay = initial_delay
                last_exception = None

                for attempt in range(1, max_retries + 1):
                    try:
                        return func(*args, **kwargs)
                    except exceptions as e:
                        last_exception = e
                        if attempt == max_retries:
                            logger.error(
                                f"Call to {func.__name__} failed after {max_retries} attempts: {str(e)}",
                                extra={"action": "retry_exhausted", "error": str(e), "attempts": max_retries}
                            )
                            raise

                        jitter_amount = random.uniform(0.01, delay * jitter_factor) if jitter else 0.0
                        sleep_time = delay + jitter_amount

                        retry_info = {
                            "attempt": attempt,
                            "base_delay": round(delay, 4),
                            "jitter": round(jitter_amount, 4),
                            "sleep_time": round(sleep_time, 4),
                            "error": str(e)
                        }
                        wrapper.retry_history.append(retry_info)

                        if on_retry:
                            on_retry(attempt, sleep_time, e)

                        logger.warning(
                            f"Transient error in {func.__name__} (attempt {attempt}/{max_retries}): {str(e)}. Retrying in {sleep_time:.3f}s (base: {delay}s, jitter: +{jitter_amount:.3f}s)...",
                            extra={"action": "retry_attempt", "attempt": attempt, "delay": round(sleep_time, 3)}
                        )
                        time.sleep(sleep_time)
                        delay *= backoff_factor

                raise last_exception

        wrapper.retry_history = []
        return wrapper
    return decorator


def retry_db_operation(
    max_retries: int = 3,
    initial_delay: float = 0.5,
    backoff_factor: float = 2.0,
    jitter: bool = True
):
    """
    Convenience decorator for database operations, automatically catching SQLAlchemy connection/operational errors.
    """
    try:
        from sqlalchemy.exc import OperationalError, DBAPIError
        exceptions = (OperationalError, DBAPIError, ConnectionError, TimeoutError)
    except ImportError:
        exceptions = (ConnectionError, TimeoutError)

    return retry_with_backoff(
        max_retries=max_retries,
        initial_delay=initial_delay,
        backoff_factor=backoff_factor,
        jitter=jitter,
        exceptions=exceptions
    )


def safe_groq_request(
    url: str,
    headers: dict,
    json_data: dict,
    timeout: float = 12.0,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    jitter: bool = True
) -> Optional[requests.Response]:
    """
    Resilient HTTP caller specifically for Groq API.
    Handles HTTP 429 (rate limits) and 5xx errors with exponential backoff and randomized jitter.
    """
    delay = initial_delay

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(url, headers=headers, json=json_data, timeout=timeout)

            # If rate limited (429) or server error (500, 502, 503, 504), retry
            if response.status_code == 429 or response.status_code >= 500:
                retry_after = response.headers.get("Retry-After")
                base_wait = float(retry_after) if retry_after else delay
                jitter_amount = random.uniform(0.01, base_wait * 0.25) if jitter else 0.0
                wait_time = base_wait + jitter_amount

                logger.warning(
                    f"Groq API returned HTTP {response.status_code} (attempt {attempt}/{max_retries}). Retrying in {wait_time:.3f}s (base: {base_wait}s, jitter: +{jitter_amount:.3f}s)...",
                    extra={"action": "groq_retry", "status_code": response.status_code, "attempt": attempt}
                )
                if attempt == max_retries:
                    return response
                time.sleep(wait_time)
                delay *= backoff_factor
                continue

            return response
        except (requests.RequestException, TimeoutError) as e:
            jitter_amount = random.uniform(0.01, delay * 0.25) if jitter else 0.0
            wait_time = delay + jitter_amount
            logger.warning(
                f"Groq API network error (attempt {attempt}/{max_retries}): {str(e)}. Retrying in {wait_time:.3f}s...",
                extra={"action": "groq_network_error", "attempt": attempt, "error": str(e)}
            )
            if attempt == max_retries:
                raise
            time.sleep(wait_time)
            delay *= backoff_factor

    return None
