from __future__ import annotations

import logging
from typing import Callable, List, Optional, Union
from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
    TelegramAPIError,
)
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from redis.asyncio import Redis

from tg_forced_sub.models import ForcedChannel, ChannelStatus, CheckResult, ChannelType
from tg_forced_sub.storage.base import BaseStorage
from tg_forced_sub.storage.redis_storage import RedisStorage

logger = logging.getLogger("tg_forced_sub")

DEFAULT_FORCED_SUB_TEMPLATE = (
    "🚸| عذرًا عزيزي {name}، عليك الإشتراك بقنوات البوت أولًا لتتمكن من إستخدامه:\n\n"
    "{channels}\n"
    "‼️| بعد الإشتراك، اضغط على زر التحقق بالأسفل للاستمرار."
)


class ForcedSubManager:
    """
    Central engine managing forced subscriptions, verification,
    smart rotation, multi-tenant hierarchy, and user UI.
    """

    def __init__(
        self,
        storage: Union[BaseStorage, Redis],
        cache_ttl: int = 3600,
        negative_cache_ttl: int = 6,
        max_visible_channels: Optional[int] = None,
        allow_pending_requests: bool = True,
        custom_message: str = DEFAULT_FORCED_SUB_TEMPLATE,
        check_button_text: str = "✅ تحقق من الإشتراك",
        check_callback_data: str = "fsub:check",
        auto_heal_degraded: bool = True,
        on_channel_degraded: Optional[Callable[[Union[int, str], str], None]] = None,
    ):
        if isinstance(storage, Redis):
            self.storage: BaseStorage = RedisStorage(storage)
        else:
            self.storage = storage

        self.cache_ttl = cache_ttl
        self.negative_cache_ttl = negative_cache_ttl
        self.max_visible_channels = max_visible_channels
        self.allow_pending_requests = allow_pending_requests
        self.custom_message = custom_message
        self.check_button_text = check_button_text
        self.check_callback_data = check_callback_data
        self.auto_heal_degraded = auto_heal_degraded
        self.on_channel_degraded = on_channel_degraded

    async def add_channel(
        self,
        channel_id: Union[int, str],
        title: str,
        invite_link: str,
        scope: str = "global",
        target_joins: Optional[int] = None,
        expire_seconds: Optional[int] = None,
        position: int = 0,
        ad_text: Optional[str] = None,
        channel_type: ChannelType = ChannelType.CHANNEL,
        allow_pending_request: bool = True,
    ) -> ForcedChannel:
        """Helper to quickly register a channel into storage."""
        import time
        expire_at = (int(time.time()) + expire_seconds) if (expire_seconds and expire_seconds > 0) else None

        channel = ForcedChannel(
            channel_id=channel_id,
            title=title,
            invite_link=invite_link,
            scope=str(scope),
            target_joins=target_joins,
            expire_at=expire_at,
            position=position,
            ad_text=ad_text,
            channel_type=channel_type,
            allow_pending_request=allow_pending_request,
        )
        await self.storage.add_channel(channel)
        return channel

    async def remove_channel(self, channel_id: Union[int, str], scope: str = "global") -> bool:
        """Remove a channel from storage."""
        return await self.storage.remove_channel(str(scope), channel_id)

    async def get_channels(self, scope: str = "global", active_only: bool = True) -> List[ForcedChannel]:
        """Fetch all channels registered under a scope."""
        return await self.storage.get_channels(str(scope), active_only=active_only)

    async def check_user(
        self,
        bot: Bot,
        user_id: int,
        user_first_name: str = "",
        bot_id: Optional[Union[int, str]] = None,
    ) -> CheckResult:
        """
        Comprehensive check to verify whether user has joined all required channels.
        Checks both 'global' platform channels and local 'bot_id' channels.
        """
        # 1. Fetch channels: Global + Local Bot Scope
        scopes = ["global"]
        effective_bot_id = str(bot_id) if bot_id else str(bot.id)
        if effective_bot_id != "global":
            scopes.append(effective_bot_id)

        all_channels: List[ForcedChannel] = []
        seen_channel_ids = set()

        for sc in scopes:
            channels = await self.storage.get_channels(sc, active_only=True)
            for ch in channels:
                cid_str = str(ch.channel_id)
                if cid_str not in seen_channel_ids:
                    seen_channel_ids.add(cid_str)
                    all_channels.append(ch)

        if not all_channels:
            return CheckResult(is_subscribed=True, unjoined_channels=[], cached=True, user_id=user_id)

        unjoined: List[ForcedChannel] = []
        all_cached = True

        for channel in all_channels:
            cid = channel.channel_id

            # Skip channel if currently marked as degraded (self-healing)
            if self.auto_heal_degraded and await self.storage.is_channel_degraded(cid):
                continue

            # Check positive cache first
            if await self.storage.is_user_cached(channel.scope, cid, user_id):
                continue

            all_cached = False

            # Check join request tracking
            if self.allow_pending_requests and channel.allow_pending_request:
                if await self.storage.has_pending_request(cid, user_id):
                    # User submitted a join request -> satisfied!
                    await self.storage.cache_user_subscription(
                        channel.scope, cid, user_id, self.cache_ttl
                    )
                    continue

            # Verify with Telegram API
            is_member = await self._verify_telegram_membership(bot, cid, user_id, channel)
            if is_member:
                # Cache user subscription
                await self.storage.cache_user_subscription(
                    channel.scope, cid, user_id, self.cache_ttl
                )
                # Count unique join
                await self.storage.record_user_join(channel.scope, cid, user_id)
            else:
                unjoined.append(channel)

        # Apply smart rotation (Max Visible Channels limit)
        if self.max_visible_channels and len(unjoined) > self.max_visible_channels:
            unjoined = unjoined[: self.max_visible_channels]

        return CheckResult(
            is_subscribed=(len(unjoined) == 0),
            unjoined_channels=unjoined,
            cached=all_cached,
            user_id=user_id,
            bot_id=int(effective_bot_id) if effective_bot_id.isdigit() else None,
        )

    async def _verify_telegram_membership(
        self,
        bot: Bot,
        channel_id: Union[int, str],
        user_id: int,
        channel: ForcedChannel,
    ) -> bool:
        """Call get_chat_member on Telegram API with error handling and self-healing."""
        try:
            member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            valid_statuses = {
                ChatMemberStatus.CREATOR,
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.MEMBER,
            }
            if member.status in valid_statuses:
                return True
            if member.status == ChatMemberStatus.RESTRICTED and getattr(member, "is_member", False):
                return True
            return False

        except TelegramBadRequest as e:
            err_msg = str(e).lower()
            if "user not found" in err_msg or "participant" in err_msg:
                # User simply not in channel
                return False

            if "chat not found" in err_msg or "not enough rights" in err_msg or "admin" in err_msg:
                # Bot lost privileges or channel not accessible -> Self-healing!
                logger.warning(
                    f"ForcedSub: Bot permission issue on channel {channel_id}: {e}. Marking degraded."
                )
                if self.auto_heal_degraded:
                    await self.storage.mark_channel_degraded(channel_id, duration_seconds=600)
                    if self.on_channel_degraded:
                        try:
                            self.on_channel_degraded(channel_id, str(e))
                        except Exception:
                            pass
                # Don't block user if it's bot configuration error
                return True

            logger.error(f"ForcedSub TelegramBadRequest on {channel_id}: {e}")
            return False

        except TelegramForbiddenError as e:
            # Bot was kicked from channel
            logger.warning(f"ForcedSub: Bot was kicked from channel {channel_id}. Marking degraded.")
            if self.auto_heal_degraded:
                await self.storage.mark_channel_degraded(channel_id, duration_seconds=600)
            return True

        except TelegramRetryAfter as e:
            logger.warning(f"ForcedSub FloodWait: sleep requested {e.retry_after}s")
            # In flood situations, treat as joined to avoid deadlocking users
            return True

        except TelegramAPIError as e:
            logger.error(f"ForcedSub API error checking {channel_id}: {e}")
            return False

        except Exception as e:
            logger.error(f"Unexpected error in _verify_telegram_membership: {e}")
            return False

    def format_message(
        self,
        result: CheckResult,
        user_first_name: str = "",
        template: Optional[str] = None,
    ) -> str:
        """Render the warning text with channel list and placeholders."""
        tpl = template or self.custom_message

        channels_text_lines = []
        for idx, ch in enumerate(result.unjoined_channels, start=1):
            line = f"• {idx}. <a href=\"{ch.invite_link}\">{ch.title}</a>"
            channels_text_lines.append(line)

        channels_block = "\n".join(channels_text_lines)
        first_name = user_first_name or "المستخدم"

        return tpl.format(
            name=first_name,
            user_id=result.user_id,
            channels=channels_block,
            count=len(result.unjoined_channels),
        )

    def build_keyboard(
        self,
        result: CheckResult,
        custom_buttons: Optional[List[InlineKeyboardButton]] = None,
    ) -> InlineKeyboardMarkup:
        """Construct inline keyboard containing channel links + Check button."""
        builder = InlineKeyboardBuilder()

        # One button per unjoined channel
        for ch in result.unjoined_channels:
            btn_text = f"📢 {ch.title}"
            builder.row(InlineKeyboardButton(text=btn_text, url=ch.invite_link))

        # Verification button
        check_btn = InlineKeyboardButton(
            text=self.check_button_text,
            callback_data=self.check_callback_data,
        )
        builder.row(check_btn)

        if custom_buttons:
            builder.row(*custom_buttons)

        return builder.as_markup()
