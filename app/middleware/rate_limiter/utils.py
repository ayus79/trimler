from enum import Enum

_WRAPPED_MAX_DEPTH = 10


# Atomic token bucket: refill → check → decrement → persist in one round-trip.
_LUA_TOKEN_BUCKET = """
local key    = KEYS[1]
local limit  = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local now    = tonumber(ARGV[3])

local data   = redis.call('HMGET', key, 'tokens', 'last')
local tokens = tonumber(data[1]) or limit
local last   = tonumber(data[2]) or now

local refill_rate = limit / window
tokens = math.min(limit, tokens + (now - last) * refill_rate)

redis.call('HSET', key, 'last', now)
redis.call('EXPIRE', key, window * 2)

if tokens < 1 then
    redis.call('HSET', key, 'tokens', tokens)
    return {0, 0}
end

tokens = tokens - 1
redis.call('HSET', key, 'tokens', tokens)
return {1, math.floor(tokens)}
"""


class RateLimitAlgo(Enum):
    SLIDING_WINDOW = "sliding_window"
    FIXED_WINDOW = "fixed_window"
    TOKEN_BUCKET = "token_bucket"
