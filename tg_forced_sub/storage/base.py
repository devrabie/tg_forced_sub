from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional, Union
from tg_forced_sub.models import ForcedChannel, ChannelStatus


class BaseStorage(ABC):
    """
    Abstract Base Class for forced subscription persistence and caching.
    """

    @abstractmethod
    async def add_channel(self, channel: ForcedChannel) -> bool:
        """Add or update a forced subscription channel."""
        pass

    @abstractmethod
    async def remove_channel(self, scope: str, channel_id: Union[int, str]) -> bool:
        """Remove a channel from forced subscription list."""
        pass

    @abstractmethod
    async def get_channel(self, scope: str, channel_id: Union[int, str]) -> Optional[ForcedChannel]:
        """Fetch details of a single channel."""
        pass

    @abstractmethod
    async def get_channels(self, scope: str, active_only: bool = True) -> List[ForcedChannel]:
        """Retrieve all channels for a specific scope ('global' or specific bot_id)."""
        pass

    @abstractmethod
    async def update_channel_status(
        self, scope: str, channel_id: Union[int, str], status: ChannelStatus
    ) -> bool:
        """Update status (active / paused / completed)."""
        pass

    @abstractmethod
    async def set_channel_expiration(
        self, scope: str, channel_id: Union[int, str], expire_at: Optional[int]
    ) -> bool:
        """Set or remove expiration timestamp for a channel."""
        pass

    @abstractmethod
    async def record_user_join(
        self, scope: str, channel_id: Union[int, str], user_id: int
    ) -> bool:
        """
        Record a unique user join for a channel.
        Returns True if this was a new unique join, False if already counted.
        """
        pass

    @abstractmethod
    async def is_user_cached(
        self, scope: str, channel_id: Union[int, str], user_id: int
    ) -> bool:
        """Check if user is verified as joined in cache."""
        pass

    @abstractmethod
    async def cache_user_subscription(
        self, scope: str, channel_id: Union[int, str], user_id: int, ttl: int = 3600
    ) -> None:
        """Cache verified subscription status for user."""
        pass

    @abstractmethod
    async def is_negative_cached(self, scope: str, user_id: int) -> bool:
        """Check if user verification is currently rate-limited (anti-spam)."""
        pass

    @abstractmethod
    async def set_negative_cache(self, scope: str, user_id: int, ttl: int = 8) -> None:
        """Set short cooldown on verify attempts to prevent flood."""
        pass

    @abstractmethod
    async def record_pending_request(
        self, channel_id: Union[int, str], user_id: int
    ) -> None:
        """Store pending join request submitted by user."""
        pass

    @abstractmethod
    async def has_pending_request(
        self, channel_id: Union[int, str], user_id: int
    ) -> bool:
        """Check if user has submitted a join request for this channel."""
        pass

    @abstractmethod
    async def mark_channel_degraded(
        self, channel_id: Union[int, str], duration_seconds: int = 600
    ) -> None:
        """Mark channel as degraded when bot lacks admin permissions (self-healing)."""
        pass

    @abstractmethod
    async def is_channel_degraded(self, channel_id: Union[int, str]) -> bool:
        """Check whether channel is temporarily skipped due to bot permission issues."""
        pass

    @abstractmethod
    async def reorder_channel(
        self, scope: str, channel_id: Union[int, str], position: int
    ) -> bool:
        """Set priority position for channel ordering."""
        pass
