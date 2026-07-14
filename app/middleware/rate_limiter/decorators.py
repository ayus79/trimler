from functools import wraps
from app.middleware.rate_limiter.utils import RateLimitAlgo


def rate_limit(
    limit: int, window: int, algo: RateLimitAlgo = RateLimitAlgo.SLIDING_WINDOW
):
    def decorator(fn):
        # attach to the route via functools.wraps
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            return await fn(*args, **kwargs)

        wrapper._rate_limit = {"limit": limit, "window": window, "algo": algo}
        return wrapper

    return decorator


def rate_limit_whitelist(fn):
    @wraps(fn)
    async def wrapper(*args, **kwargs):
        return await fn(*args, **kwargs)

    wrapper._rate_limit_whitelist = True
    return wrapper
