import time
from collections import defaultdict
from typing import Dict, List, Tuple
from fastapi import Request, HTTPException, status


class SlidingWindowRateLimiter:
    """
    In-memory sliding window rate limiter.
    Cleans up expired timestamps on each check.
    """
    def __init__(self, default_limit: int = 60, window_seconds: int = 60):
        self.default_limit = default_limit
        self.window_seconds = window_seconds
        self.requests: Dict[str, List[float]] = defaultdict(list)

    def is_allowed(
        self,
        key: str,
        max_requests: int = None,
        window_seconds: int = None
    ) -> Tuple[bool, int]:
        limit = max_requests or self.default_limit
        window = window_seconds or self.window_seconds
        now = time.time()
        cutoff = now - window

        # Filter out timestamps older than the sliding window
        valid_timestamps = [t for t in self.requests[key] if t > cutoff]
        self.requests[key] = valid_timestamps

        if len(valid_timestamps) >= limit:
            # Calculate remaining seconds before the oldest request expires
            oldest = valid_timestamps[0]
            retry_after = max(1, int(oldest + window - now))
            return False, retry_after

        # Record this request
        self.requests[key].append(now)
        return True, 0


# Global instance
limiter = SlidingWindowRateLimiter(default_limit=60, window_seconds=60)


async def check_rate_limit(request: Request, max_requests: int = 60, window_seconds: int = 60):
    """
    FastAPI dependency / middleware check.
    Uses Client IP + optional session_id from query params.
    """
    client_ip = request.client.host if request.client else "unknown"
    session_id = request.query_params.get("session_id", "")
    key = f"{client_ip}:{session_id}" if session_id else client_ip

    allowed, retry_after = limiter.is_allowed(key, max_requests=max_requests, window_seconds=window_seconds)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Please retry after {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)}
        )
