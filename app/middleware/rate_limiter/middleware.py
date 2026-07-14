import time
from typing import Optional, Set
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from app.middleware.rate_limiter.limiter import RateLimiter
from app.middleware.rate_limiter.utils import _WRAPPED_MAX_DEPTH, RateLimitAlgo


class RateLimitFastAPIMiddleware(BaseHTTPMiddleware):

    def __init__(
        self,
        app,
        rate_limiter: Optional[RateLimiter] = None,
        default_limit: int = 100,
        default_window: int = 60,
        default_algo: RateLimitAlgo = RateLimitAlgo.SLIDING_WINDOW,
        enable_bot_detection: bool = False,
        trusted_proxies: Optional[Set[str]] = None,
    ):
        super().__init__(app)
        self.rate_limiter = rate_limiter or RateLimiter(trusted_proxies=trusted_proxies)
        self.default_limit = default_limit
        self.default_window = default_window
        self.default_algo = default_algo
        self.enable_bot_detection = enable_bot_detection
        self.trusted_proxies: Set[str] = trusted_proxies or set()

    def _get_client_ip(self, request: Request) -> str:
        direct_ip = request.client.host if request.client else None

        # Only trust X-Forwarded-For when the direct connection is from a known proxy.
        if direct_ip in self.trusted_proxies:
            forwarded_for = request.headers.get("x-forwarded-for", "")
            if forwarded_for:
                return forwarded_for.split(",")[0].strip()

        return direct_ip or "unknown"

    async def dispatch(self, request: Request, call_next):
        route = request.scope.get("route")
        endpoint = getattr(route, "endpoint", None)

        # Unwrap decorators, guarded against circular __wrapped__ references.
        depth = 0
        while hasattr(endpoint, "__wrapped__") and depth < _WRAPPED_MAX_DEPTH:
            endpoint = endpoint.__wrapped__
            depth += 1

        if endpoint and getattr(endpoint, "_rate_limit_whitelist", False):
            return await call_next(request)

        ip = self._get_client_ip(request)
        key = f"{ip}:{request.url.path}"

        limit = self.default_limit
        window = self.default_window
        algo = self.default_algo

        if endpoint and hasattr(endpoint, "_rate_limit"):
            cfg = endpoint._rate_limit
            limit = cfg["limit"]
            window = cfg["window"]
            algo = cfg["algo"]

        allowed, remaining = await self.rate_limiter.allow(
            key=key,
            limit=limit,
            window=window,
            algo=algo,
            enable_bot_detection=self.enable_bot_detection,
        )

        if not allowed:
            return JSONResponse(
                content={"status": False, "message": "Too many requests"},
                status_code=429,
                headers={
                    "Retry-After": str(window),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + window),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(time.time()) + window)

        return response
