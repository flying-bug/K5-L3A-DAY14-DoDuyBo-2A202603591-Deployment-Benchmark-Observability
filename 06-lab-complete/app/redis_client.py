"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

App vẫn phải khởi động được khi Redis chưa sẵn sàng (không ping lúc import,
vì redis.from_url chỉ tạo connection pool, không mở connection ngay).
"""
import redis

from app.config import settings

r = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)


def redis_healthy() -> bool:
    try:
        return bool(r.ping())
    except redis.RedisError:
        return False
