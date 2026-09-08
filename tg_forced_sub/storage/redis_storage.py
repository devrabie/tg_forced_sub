from __future__ import annotations

import json
from typing import List, Optional, Union
from redis.asyncio import Redis

from tg_forced_sub.models import ForcedChannel, ChannelStatus
from tg_forced_sub.storage.base import BaseStorage


class RedisStorage(BaseStorage):
    """
    High-performance, async Redis storage implementation for forced subscription,
    caching, join requests tracking, and rate limiting.
    """

    def __init__(self, redis: Redis, key_prefix: str = "fsub"):
        self.redis = redis
        self.prefix = key_prefix

    def _scope_channels_key(self, scope: str) -> str:
        return f"{self.prefix}:{scope}:channels"

    def _channel_key(self, scope: str, channel_id: Union[int, str]) -> str:
        return f"{self.prefix}:{scope}:channel:{channel_id}"

    def _user_cache_key(self, scope: str, channel_id: Union[int, str], user_id: int) -> str:
        return f"{self.prefix}:cache:{scope}:{channel_id}:{user_id}"

    def _neg_cache_key(self, scope: str, user_id: int) -> str:
        return f"{self.prefix}:neg_cache:{scope}:{user_id}"

    def _counted_joins_key(self, scope: str, channel_id: Union[int, str]) -> str:
        return f"{self.prefix}:counted:{scope}:{channel_id}"

    def _pending_key(self, channel_id: Union[int, str]) -> str:
        return f"{self.prefix}:pending:{channel_id}"

    def _degraded_key(self, channel_id: Union[int, str]) -> str:
        return f"{self.prefix}:degraded:{channel_id}"

    async def add_channel(self, channel: ForcedChannel) -> bool:
        channel_key = self._channel_key(channel.scope, channel.channel_id)
        scope_key = self._scope_channels_key(channel.scope)

        data = channel.model_dump_json()

        pipe = self.redis.pipeline()
        pipe.sadd(scope_key, str(channel.channel_id))
        pipe.set(channel_key, data)

        # If channel has expiration timestamp, set TTL on key if desired
        if channel.expire_at is not None and channel.expire_at > 0:
            ttl = channel.remaining_ttl
            if ttl and ttl > 0:
                pipe.expire(channel_key, ttl)

        await pipe.execute()
        return True

    async def remove_channel(self, scope: str, channel_id: Union[int, str]) -> bool:
        channel_key = self._channel_key(scope, channel_id)
        scope_key = self._scope_channels_key(scope)
        counted_key = self._counted_joins_key(scope, channel_id)

        pipe = self.redis.pipeline()
        pipe.srem(scope_key, str(channel_id))
        pipe.delete(channel_key)
        pipe.delete(counted_key)
        res = await pipe.execute()
        return bool(res[0])

    async def get_channel(self, scope: str, channel_id: Union[int, str]) -> Optional[ForcedChannel]:
        channel_key = self._channel_key(scope, channel_id)
        raw_data = await self.redis.get(channel_key)
        if not raw_data:
            # Clean up dangling member from set
            await self.redis.srem(self._scope_channels_key(scope), str(channel_id))
            return None

        data_str = raw_data.decode("utf-8") if isinstance(raw_data, bytes) else raw_data
        try:
            channel = ForcedChannel.model_validate_json(data_str)
            # Auto-handle expiration
            if channel.is_expired:
                await self.remove_channel(scope, channel_id)
                return None
            return channel
        except Exception:
            return None

    async def get_channels(self, scope: str, active_only: bool = True) -> List[ForcedChannel]:
        scope_key = self._scope_channels_key(scope)
        channel_ids = await self.redis.smembers(scope_key)
        if not channel_ids:
            return []

        channels: List[ForcedChannel] = []
        for cid_bytes in channel_ids:
            cid = cid_bytes.decode("utf-8") if isinstance(cid_bytes, bytes) else str(cid_bytes)
            ch = await self.get_channel(scope, cid)
            if ch is None:
                continue
            if active_only and not ch.is_available:
                continue
            channels.append(ch)

        # Sort by position DESC, created_at ASC
        channels.sort(key=lambda c: (c.position, -c.created_at), reverse=True)
        return channels

    async def update_channel_status(
        self, scope: str, channel_id: Union[int, str], status: ChannelStatus
    ) -> bool:
        ch = await self.get_channel(scope, channel_id)
        if not ch:
            return False
        ch.status = status
        return await self.add_channel(ch)

    async def set_channel_expiration(
        self, scope: str, channel_id: Union[int, str], expire_at: Optional[int]
    ) -> bool:
        ch = await self.get_channel(scope, channel_id)
        if not ch:
            return False
        ch.expire_at = expire_at
        return await self.add_channel(ch)

    async def record_user_join(
        self, scope: str, channel_id: Union[int, str], user_id: int
    ) -> bool:
        counted_key = self._counted_joins_key(scope, channel_id)
        is_new = await self.redis.sadd(counted_key, str(user_id))
        if is_new:
            ch = await self.get_channel(scope, channel_id)
            if ch:
                ch.current_joins += 1
                if ch.is_quota_reached:
                    ch.status = ChannelStatus.COMPLETED
                await self.add_channel(ch)
            return True
        return False

    async def is_user_cached(
        self, scope: str, channel_id: Union[int, str], user_id: int
    ) -> bool:
        key = self._user_cache_key(scope, channel_id, user_id)
        return bool(await self.redis.exists(key))

    async def cache_user_subscription(
        self, scope: str, channel_id: Union[int, str], user_id: int, ttl: int = 3600
    ) -> None:
        if ttl <= 0:
            return
        key = self._user_cache_key(scope, channel_id, user_id)
        await self.redis.set(key, "1", ex=ttl)

    async def is_negative_cached(self, scope: str, user_id: int) -> bool:
        key = self._neg_cache_key(scope, user_id)
        return bool(await self.redis.exists(key))

    async def set_negative_cache(self, scope: str, user_id: int, ttl: int = 8) -> None:
        if ttl <= 0:
            return
        key = self._neg_cache_key(scope, user_id)
        await self.redis.set(key, "1", ex=ttl)

    async def record_pending_request(
        self, channel_id: Union[int, str], user_id: int
    ) -> None:
        key = self._pending_key(channel_id)
        # Keep pending status for 7 days (604800s)
        pipe = self.redis.pipeline()
        pipe.sadd(key, str(user_id))
        pipe.expire(key, 604800)
        await pipe.execute()

    async def has_pending_request(
        self, channel_id: Union[int, str], user_id: int
    ) -> bool:
        key = self._pending_key(channel_id)
        return bool(await self.redis.sismember(key, str(user_id)))

    async def mark_channel_degraded(
        self, channel_id: Union[int, str], duration_seconds: int = 600
    ) -> None:
        key = self._degraded_key(channel_id)
        await self.redis.set(key, "1", ex=duration_seconds)

    async def is_channel_degraded(self, channel_id: Union[int, str]) -> bool:
        key = self._degraded_key(channel_id)
        return bool(await self.redis.exists(key))

    async def reorder_channel(
        self, scope: str, channel_id: Union[int, str], position: int
    ) -> bool:
        ch = await self.get_channel(scope, channel_id)
        if not ch:
            return False
        ch.position = position
        return await self.add_channel(ch)

    def _active_prompt_key(self, scope: str, user_id: int) -> str:
        return f"{self.prefix}:prompt:{scope}:{user_id}"

    async def save_active_prompt(
        self, scope: str, user_id: int, chat_id: int, message_id: int, ttl: int = 86400
    ) -> None:
        key = self._active_prompt_key(scope, user_id)
        payload = json.dumps({"chat_id": chat_id, "message_id": message_id})
        await self.redis.set(key, payload, ex=ttl)

    async def get_active_prompt(
        self, scope: str, user_id: int
    ) -> Optional[dict]:
        key = self._active_prompt_key(scope, user_id)
        raw = await self.redis.get(key)
        if not raw:
            return None
        raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        try:
            return json.loads(raw_str)
        except Exception:
            return None

    async def clear_active_prompt(self, scope: str, user_id: int) -> None:
        key = self._active_prompt_key(scope, user_id)
        await self.redis.delete(key)

    async def invalidate_user_cache(
        self, scope: str, channel_id: Union[int, str], user_id: int
    ) -> None:
        # Invalidate both specific scope and global cache for safety
        keys = [
            self._user_cache_key(scope, channel_id, user_id),
            self._user_cache_key("global", channel_id, user_id),
        ]
        await self.redis.delete(*keys)
