import redis
from django.conf import settings

from apps.datasets.models import Dataset

_redis_client: redis.Redis | None = None


def _get_redis_client() -> redis.Redis:
    """全局单例 Redis 客户端（复用连接池，避免每次 new UploadLockService 都新建连接）。"""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL)
    return _redis_client


class UploadLockService:
    """文件上传幂等性服务

    双重保障：
    1. Redis SETNX 分布式锁（第一道防线）—— 防止并发重复处理
    2. 数据库 (owner, file_md5) 唯一约束（第二道防线）—— 防止重复记录

    锁 key 包含 user_id，因为唯一约束是 (owner, file_md5) 而非全局唯一。
    不同用户可以上传相同文件。
    """

    LOCK_TIMEOUT = 300  # 5分钟过期，防止死锁

    def __init__(self):
        self.redis_client = _get_redis_client()

    def try_acquire_lock(self, user_id, file_md5: str) -> bool:
        lock_key = f'upload_lock:{user_id}:{file_md5}'
        acquired = self.redis_client.set(
            lock_key, '1', nx=True, ex=self.LOCK_TIMEOUT
        )
        return bool(acquired)

    def release_lock(self, user_id, file_md5: str):
        lock_key = f'upload_lock:{user_id}:{file_md5}'
        self.redis_client.delete(lock_key)

    def is_duplicate(self, user_id, file_md5: str) -> bool:
        return Dataset.objects.filter(
            owner_id=user_id, file_md5=file_md5
        ).exists()
