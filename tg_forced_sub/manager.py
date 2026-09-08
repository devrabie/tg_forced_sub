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

from tg_forced_sub.models import (
    ForcedChannel,
    ChannelStatus,
    CheckResult,
    ChannelType,
    ChannelCategory,
)
from tg_forced_sub.storage.base import BaseStorage
from tg_forced_sub.storage.redis_storage import RedisStorage

logger = logging.getLogger("tg_forced_sub")

DEFAULT_FORCED_SUB_TEMPLATE = (
    "🚸| عذرًا عزيزي {name}، عليك الإشتراك بقنوات البوت أولًا لتتمكن من إستخدامه:\n\n"
    "{channels}\n"
    "‼️| بعد الإشتراك، اضغط على زر التحقق بالأسفل للاستمرار."
)

DEFAULT_LINK_PROMO_TEMPLATE = (
    "📢 <b>إعلان مميز</b>\n"
    "━━━━━━━━━━━━━━━━━\n\n"
    "عزيزي {name}، يرجى زيارة الرابط التالي لدعم البوت والاستمرار في استخدامه:\n\n"
    "{channels}\n"
    "اضغط على الرابط أعلاه ثم اضغط على زر المتابعة بالأسفل للاستمرار."
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
        link_message: str = DEFAULT_LINK_PROMO_TEMPLATE,
        check_button_text: str = "✅ تحقق من الإشتراك",
        check_callback_data: str = "fsub:check",
        continue_button_text: str = "تابع استخدام البوت ◀️",
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
        self.link_message = link_message
        self.check_button_text = check_button_text
        self.check_callback_data = check_callback_data
        self.continue_button_text = continue_button_text
        self.auto_heal_degraded = auto_heal_degraded
        self.on_channel_degraded = on_channel_degraded

    async def add_channel(
        self,
        channel_id: Union[int, str],
        title: str,
        invite_link: str,
        category: ChannelCategory = ChannelCategory.PRIMARY,
        scope: str = "global",
        target_joins: Optional[int] = None,
        expire_seconds: Optional[int] = None,
        position: int = 0,
        ad_text: Optional[str] = None,
        channel_type: ChannelType = ChannelType.CHANNEL,
        frequency_cap: int = 2,
        frequency_period: int = 86400,
        allow_pending_request: bool = True,
    ) -> ForcedChannel:
        """Helper to quickly register a channel into storage."""
        import time
        expire_at = (int(time.time()) + expire_seconds) if (expire_seconds and expire_seconds > 0) else None

        channel = ForcedChannel(
            channel_id=channel_id,
            title=title,
            invite_link=invite_link,
            category=category,
            scope=str(scope),
            target_joins=target_joins,
            expire_at=expire_at,
            position=position,
            ad_text=ad_text,
            channel_type=channel_type,
            frequency_cap=frequency_cap,
            frequency_period=frequency_period,
            allow_pending_request=allow_pending_request,
        )
        await self.storage.add_channel(channel)
        return channel

    async def add_link(
        self,
        link_id: Union[int, str],
        title: str,
        url: str,
        scope: str = "global",
        ad_text: Optional[str] = None,
        frequency_cap: int = 2,
        frequency_period: int = 86400,
        expire_seconds: Optional[int] = None,
    ) -> ForcedChannel:
        """Helper to register a direct promo link (no telegram check, frequency capped)."""
        return await self.add_channel(
            channel_id=link_id,
            title=title,
            invite_link=url,
            category=ChannelCategory.LINK,
            scope=scope,
            ad_text=ad_text,
            frequency_cap=frequency_cap,
            frequency_period=frequency_period,
            expire_seconds=expire_seconds,
            channel_type=ChannelType.DIRECT_LINK,
        )

    async def remove_channel(self, channel_id: Union[int, str], scope: str = "global") -> bool:
        """Remove a channel from storage."""
        return await self.storage.remove_channel(str(scope), channel_id)

    async def get_channels(
        self,
        scope: str = "global",
        category: Optional[ChannelCategory] = None,
        active_only: bool = True
    ) -> List[ForcedChannel]:
        """Fetch all channels registered under a scope, optionally filtered by category."""
        channels = await self.storage.get_channels(str(scope), active_only=active_only)
        if category:
            channels = [c for c in channels if c.category == category]
        return channels

    async def move_channel_to_top(self, channel_id: Union[int, str], scope: str = "global") -> bool:
        """Move a channel to the top of its category priority list."""
        return await self.storage.move_to_top(str(scope), channel_id)

    async def toggle_channel_status(self, channel_id: Union[int, str], scope: str = "global") -> Optional[ChannelStatus]:
        """Toggle a channel status between active and paused."""
        ch = await self.storage.get_channel(str(scope), channel_id)
        if not ch:
            return None
        new_status = ChannelStatus.PAUSED if ch.status == ChannelStatus.ACTIVE else ChannelStatus.ACTIVE
        ch.status = new_status
        await self.storage.add_channel(ch)
        return new_status

    async def set_channel_ttl(self, channel_id: Union[int, str], ttl_seconds: int, scope: str = "global") -> bool:
        """Set channel expiration in seconds (0 = permanent)."""
        import time
        ch = await self.storage.get_channel(str(scope), channel_id)
        if not ch:
            return False
        ch.expire_at = (int(time.time()) + ttl_seconds) if ttl_seconds > 0 else None
        return await self.storage.add_channel(ch)

    async def check_user(
        self,
        bot: Bot,
        user_id: int,
        user_first_name: str = "",
        bot_id: Optional[Union[int, str]] = None,
    ) -> CheckResult:
        """
        Comprehensive 3-tier check:
        Tier 1: PRIMARY channels (Sequential: strictly one by one in order of position DESC).
        Tier 2: SECONDARY channels (Combined: all unjoined secondary channels in one message).
        Tier 3: DIRECT PROMO LINKS (Frequency Capped: shows if under impression cap within period).
        """
        scopes = ["global"]
        effective_bot_id = str(bot_id) if bot_id else str(bot.id)
        if effective_bot_id != "global":
            scopes.append(effective_bot_id)

        all_channels: List[ForcedChannel] = []
        seen_channel_ids = set()

        for sc in scopes:
            channels = await self.storage.get_channels(sc, active_only=True)
            for ch in channels:
                cid_str = f"{sc}:{ch.channel_id}"
                if cid_str not in seen_channel_ids:
                    seen_channel_ids.add(cid_str)
                    all_channels.append(ch)

        if not all_channels:
            return CheckResult(is_subscribed=True, unjoined_channels=[], cached=True, user_id=user_id)

        # Separate items by category
        primary_channels = [c for c in all_channels if c.category == ChannelCategory.PRIMARY]
        secondary_channels = [c for c in all_channels if c.category == ChannelCategory.SECONDARY]
        link_channels = [c for c in all_channels if c.category == ChannelCategory.LINK]

        # Sort primary channels by position DESC, then created_at ASC
        primary_channels.sort(key=lambda c: (-c.position, c.created_at))

        # --- TIER 1: PRIMARY CHANNELS (Sequential) ---
        for channel in primary_channels:
            cid = channel.channel_id
            if self.auto_heal_degraded and await self.storage.is_channel_degraded(cid):
                continue
            if await self.storage.is_user_cached(channel.scope, cid, user_id):
                continue
            if self.allow_pending_requests and channel.allow_pending_request:
                if await self.storage.has_pending_request(cid, user_id):
                    await self.storage.cache_user_subscription(channel.scope, cid, user_id, self.cache_ttl)
                    continue

            is_member = await self._verify_telegram_membership(bot, cid, user_id, channel)
            if is_member:
                await self.storage.cache_user_subscription(channel.scope, cid, user_id, self.cache_ttl)
                await self.storage.record_user_join(channel.scope, cid, user_id)
            else:
                # Sequential: Return immediately with this single primary channel
                return CheckResult(
                    is_subscribed=False,
                    unjoined_channels=[channel],
                    category=ChannelCategory.PRIMARY,
                    cached=False,
                    user_id=user_id,
                    bot_id=int(effective_bot_id) if effective_bot_id.isdigit() else None,
                )

        # --- TIER 2: SECONDARY CHANNELS (Combined) ---
        unjoined_secondary = []
        for channel in secondary_channels:
            cid = channel.channel_id
            if self.auto_heal_degraded and await self.storage.is_channel_degraded(cid):
                continue
            if await self.storage.is_user_cached(channel.scope, cid, user_id):
                continue
            if self.allow_pending_requests and channel.allow_pending_request:
                if await self.storage.has_pending_request(cid, user_id):
                    await self.storage.cache_user_subscription(channel.scope, cid, user_id, self.cache_ttl)
                    continue

            is_member = await self._verify_telegram_membership(bot, cid, user_id, channel)
            if is_member:
                await self.storage.cache_user_subscription(channel.scope, cid, user_id, self.cache_ttl)
                await self.storage.record_user_join(channel.scope, cid, user_id)
            else:
                unjoined_secondary.append(channel)

        if unjoined_secondary:
            if self.max_visible_channels and len(unjoined_secondary) > self.max_visible_channels:
                unjoined_secondary = unjoined_secondary[:self.max_visible_channels]
            return CheckResult(
                is_subscribed=False,
                unjoined_channels=unjoined_secondary,
                category=ChannelCategory.SECONDARY,
                cached=False,
                user_id=user_id,
                bot_id=int(effective_bot_id) if effective_bot_id.isdigit() else None,
            )

        # --- TIER 3: DIRECT PROMO LINKS (Without check, frequency capped) ---
        for link in link_channels:
            lid = link.channel_id
            should_show = await self.storage.check_and_record_link_impression(
                link.scope, lid, user_id, cap=link.frequency_cap, period=link.frequency_period
            )
            if should_show:
                await self.storage.increment_link_views(link.scope, lid)
                return CheckResult(
                    is_subscribed=False,
                    unjoined_channels=[link],
                    category=ChannelCategory.LINK,
                    active_link=link,
                    cached=False,
                    user_id=user_id,
                    bot_id=int(effective_bot_id) if effective_bot_id.isdigit() else None,
                )

        # All tiers satisfied!
        return CheckResult(
            is_subscribed=True,
            unjoined_channels=[],
            cached=True,
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
        """Render the warning or promotional text with channel list or link and placeholders."""
        first_name = user_first_name or "المستخدم"

        # Special handling for LINK category
        if result.category == ChannelCategory.LINK and result.unjoined_channels:
            link = result.unjoined_channels[0]
            if link.ad_text:
                return link.ad_text.replace("@اسم", first_name).replace("@رابط", link.invite_link)
            tpl = template or self.link_message
            link_block = f"🔗 <a href=\"{link.invite_link}\">{link.title}</a>"
            return tpl.format(
                name=first_name,
                user_id=result.user_id,
                channels=link_block,
                count=1,
            )

        tpl = template or self.custom_message

        channels_text_lines = []
        for idx, ch in enumerate(result.unjoined_channels, start=1):
            line = f"• {idx}. <a href=\"{ch.invite_link}\">{ch.title}</a>"
            channels_text_lines.append(line)

        channels_block = "\n".join(channels_text_lines)

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
        """Construct inline keyboard containing channel links + Check / Continue button."""
        builder = InlineKeyboardBuilder()

        # If it's a LINK category:
        if result.category == ChannelCategory.LINK and result.unjoined_channels:
            link = result.unjoined_channels[0]
            btn_text = f"🔗 {link.title}"
            builder.row(InlineKeyboardButton(text=btn_text, url=link.invite_link))
            cont_btn = InlineKeyboardButton(
                text=self.continue_button_text,
                callback_data=self.check_callback_data,
            )
            builder.row(cont_btn)
            if custom_buttons:
                builder.row(*custom_buttons)
            return builder.as_markup()

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

    async def save_active_prompt(
        self, scope: str, user_id: int, chat_id: int, message_id: int, ttl: int = 86400
    ) -> None:
        """Store active prompt message coordinates for real-time updating."""
        await self.storage.save_active_prompt(scope, user_id, chat_id, message_id, ttl)

    async def get_active_prompt(self, scope: str, user_id: int) -> Optional[dict]:
        """Retrieve active prompt coordinates."""
        return await self.storage.get_active_prompt(scope, user_id)

    async def clear_active_prompt(self, scope: str, user_id: int) -> None:
        """Clear active prompt message."""
        await self.storage.clear_active_prompt(scope, user_id)

    async def on_member_joined(
        self,
        bot: Bot,
        channel_id: Union[int, str],
        user_id: int,
        user_first_name: str = "",
        bot_id: Optional[Union[int, str]] = None,
    ) -> None:
        """
        Triggered in real-time when a user joins a managed channel.
        Caches subscription, counts join, and automatically updates or clears active prompt message.
        """
        scope = str(bot_id) if bot_id else str(bot.id)
        cid = str(channel_id)

        # 1. Cache user as subscribed
        await self.storage.cache_user_subscription(scope, cid, user_id, self.cache_ttl)
        await self.storage.cache_user_subscription("global", cid, user_id, self.cache_ttl)
        await self.storage.record_user_join(scope, cid, user_id)
        await self.storage.record_user_join("global", cid, user_id)

        # 2. Check if user has an active prompt message
        active_prompt = await self.storage.get_active_prompt(scope, user_id)
        if not active_prompt:
            active_prompt = await self.storage.get_active_prompt("global", user_id)

        if not active_prompt:
            return

        chat_id = active_prompt["chat_id"]
        message_id = active_prompt["message_id"]

        # 3. Check remaining subscription requirements
        result = await self.check_user(
            bot=bot,
            user_id=user_id,
            user_first_name=user_first_name,
            bot_id=bot_id,
        )

        try:
            if result.is_subscribed:
                # All channels joined! Update message to celebrate and allow usage
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text="✅ <b>تم التحقق تلقائياً من اشتراكك بنجاح!</b>\nشكراً لك، يمكنك الآن استخدام البوت بحرية.",
                    parse_mode="HTML",
                )
                await self.storage.clear_active_prompt(scope, user_id)
            else:
                # Some channels remain: dynamically update buttons and text!
                # The channel the user just joined is now excluded from the keyboard!
                text = self.format_message(result, user_first_name)
                keyboard = self.build_keyboard(result)
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e).lower():
                logger.debug(f"Live update message failed: {e}")
        except Exception as e:
            logger.debug(f"Unexpected error in live UI update: {e}")

    async def on_member_left(
        self,
        channel_id: Union[int, str],
        user_id: int,
        bot_id: Optional[Union[int, str]] = None,
    ) -> None:
        """
        Triggered in real-time when a user leaves a managed channel.
        Instantly invalidates cached membership so forced subscription re-triggers.
        """
        scope = str(bot_id) if bot_id else "global"
        await self.storage.invalidate_user_cache(scope, channel_id, user_id)
        logger.info(f"Invalidated forced sub cache for user {user_id} leaving channel {channel_id}")

