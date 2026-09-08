from __future__ import annotations

import time
from enum import Enum
from typing import Optional, Union, List
from pydantic import BaseModel, Field


class ChannelStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class ChannelType(str, Enum):
    CHANNEL = "channel"
    SUPERGROUP = "supergroup"
    CHAT_FOLDER = "chat_folder"


class ForcedChannel(BaseModel):
    """
    Represents a forced subscription channel / chat or folder.
    """
    channel_id: Union[int, str] = Field(
        ...,
        description="Telegram Chat ID (e.g. -1001234567890) or username (@channel) or folder ID"
    )
    title: str = Field(..., description="Channel name or title shown to users")
    invite_link: str = Field(..., description="Invite link or t.me link")
    status: ChannelStatus = Field(default=ChannelStatus.ACTIVE, description="Current channel status")
    channel_type: ChannelType = Field(default=ChannelType.CHANNEL, description="Type of chat/channel")
    
    target_joins: Optional[int] = Field(
        default=None,
        description="Quota: target number of subscribers to reach before auto-pausing/completing"
    )
    current_joins: int = Field(default=0, description="Total unique joins recorded via bot")
    
    expire_at: Optional[int] = Field(
        default=None,
        description="Unix timestamp when this channel's forced subscription expires"
    )
    position: int = Field(default=0, description="Ordering priority (higher number = top)")
    ad_text: Optional[str] = Field(default=None, description="Optional custom promotional text")
    
    allow_pending_request: bool = Field(
        default=True,
        description="Whether a pending join request satisfies the subscription condition"
    )
    scope: str = Field(
        default="global",
        description="'global' for factory-wide channels, or specific bot_id string for child bots"
    )
    created_at: int = Field(
        default_factory=lambda: int(time.time()),
        description="Creation timestamp"
    )

    @property
    def is_expired(self) -> bool:
        """Check if channel expiration timestamp has passed."""
        if self.expire_at is not None and self.expire_at > 0:
            return time.time() >= self.expire_at
        return False

    @property
    def remaining_ttl(self) -> Optional[int]:
        """Returns remaining seconds before expiration, or None if permanent."""
        if self.expire_at is not None and self.expire_at > 0:
            rem = int(self.expire_at - time.time())
            return max(0, rem)
        return None

    @property
    def is_quota_reached(self) -> bool:
        """Check if the target join quota has been reached."""
        if self.target_joins is not None and self.target_joins > 0:
            return self.current_joins >= self.target_joins
        return False

    @property
    def is_available(self) -> bool:
        """Check if channel is currently eligible to be displayed to users."""
        if self.status != ChannelStatus.ACTIVE:
            return False
        if self.is_expired:
            return False
        if self.is_quota_reached:
            return False
        return True


class CheckResult(BaseModel):
    """
    Result of verifying a user's subscription status.
    """
    is_subscribed: bool
    unjoined_channels: List[ForcedChannel] = Field(default_factory=list)
    cached: bool = False
    user_id: int
    bot_id: Optional[int] = None
