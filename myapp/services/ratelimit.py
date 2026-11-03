import time
from functools import wraps

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse


def hit(user_id, bucket):
    """Records one call. Returns (allowed, retry_after_seconds)."""
    limit, window = settings.AI_RATE_LIMITS[bucket]
    key = f"rl:{bucket}:{user_id}"
    now = time.time()
    stamps = [t for t in cache.get(key, []) if now - t < window]
    if len(stamps) >= limit:
        return False, int(window - (now - stamps[0])) + 1
    stamps.append(now)
    cache.set(key, stamps, window)
    return True, 0


def rate_limited(bucket):
    """Decorator for plain Django JSON views or DRF `post` methods (request is the last positional arg)."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            request = next(a for a in args if hasattr(a, "user"))
            allowed, wait = hit(request.user.pk, bucket)
            if not allowed:
                resp = JsonResponse({"ok": False, "code": "rate_limited",
                                     "error": f"You have used the hourly limit for this tool. Try again in {max(1, wait // 60)} min."},
                                    status=429)
                resp["Retry-After"] = str(wait)
                return resp
            return fn(*args, **kwargs)
        return wrapper
    return deco
