from __future__ import annotations

import logging
from typing import Optional, Union
from aiogram import Bot, Dispatcher, Router, F
from aiogram.enums import ChatMemberStatus
from aiogram.types import CallbackQuery, ChatJoinRequest, ChatMemberUpdated, Message
from aiogram.exceptions import TelegramBadRequest

from tg_forced_sub.manager import ForcedSubManager

logger = logging.getLogger("tg_forced_sub")


def create_forced_sub_router(manager: ForcedSubManager) -> Router:
    """
    Creates and returns an aiogram Router pre-configured with:
    1. Callback handler for the 'Check Subscription' button (with anti-spam).
    2. ChatJoinRequest handler to track pending requests for join-request channels.
    """
    router = Router(name="tg_forced_sub_router")

    @router.callback_query(F.data == manager.check_callback_data)
    async def on_check_subscription(callback: CallbackQuery, bot: Bot):
        user = callback.from_user
        if not user:
            return

        effective_scope = str(bot.id)

        # 1. Anti-spam / Negative Cache check
        if await manager.storage.is_negative_cached(effective_scope, user.id):
            await callback.answer(
                "⏳ تم فحص اشتراكك للتو، يرجى الانتظار بضع ثوانٍ قبل المحاولة مجدداً.",
                show_alert=True,
            )
            return

        # Set negative cooldown (anti-spam)
        await manager.storage.set_negative_cache(
            effective_scope, user.id, ttl=manager.negative_cache_ttl
        )

        # 2. Check subscription status
        result = await manager.check_user(
            bot=bot,
            user_id=user.id,
            user_first_name=user.first_name,
            bot_id=bot.id,
        )

        # 3. If successfully joined all channels
        if result.is_subscribed:
            await callback.answer(
                "✅ تم التحقق من اشتراكك بنجاح! يمكنك الآن استخدام البوت بحرية.",
                show_alert=True,
            )
            if callback.message:
                try:
                    # Clean up the forced subscription message
                    await callback.message.delete()
                except TelegramBadRequest:
                    try:
                        await callback.message.edit_text(
                            "✅ <b>تم التحقق من اشتراكك بنجاح!</b>\nأرسل /start لبدء الاستخدام.",
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass
            return

        # 4. If still missing channels
        await callback.answer(
            f"⚠️ لم تشترك بعد في جميع القنوات! متبقي ({len(result.unjoined_channels)}) قناة.",
            show_alert=True,
        )

        # Refresh prompt message with remaining channels
        if callback.message:
            text = manager.format_message(result, user.first_name)
            keyboard = manager.build_keyboard(result)
            try:
                await callback.message.edit_text(
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            except TelegramBadRequest as e:
                if "message is not modified" not in str(e).lower():
                    logger.warning(f"Error editing fsub message: {e}")

    @router.chat_join_request()
    async def on_chat_join_request(event: ChatJoinRequest):
        """
        Automatically captures join requests to channels where the bot is admin,
        allowing users to be validated immediately if allow_pending_requests=True.
        """
        user_id = event.from_user.id
        channel_id = event.chat.id
        await manager.storage.record_pending_request(channel_id, user_id)
        logger.info(f"Recorded pending join request: user={user_id} in channel={channel_id}")

    @router.chat_member()
    async def on_chat_member_updated(event: ChatMemberUpdated, bot: Bot):
        """
        Listens to real-time member join and leave events across managed channels.
        - When a user joins: immediately caches membership, records join, and updates/removes
          the active forced subscription prompt message in real-time!
        - When a user leaves: immediately revokes their cached membership so forced sub re-engages.
        """
        user = event.new_chat_member.user
        if not user or user.is_bot:
            return

        channel_id = event.chat.id
        old_status = event.old_chat_member.status
        new_status = event.new_chat_member.status

        active_statuses = {
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR,
        }

        was_member = old_status in active_statuses or (
            old_status == ChatMemberStatus.RESTRICTED and getattr(event.old_chat_member, "is_member", False)
        )
        is_member = new_status in active_statuses or (
            new_status == ChatMemberStatus.RESTRICTED and getattr(event.new_chat_member, "is_member", False)
        )

        # 1. User Joined the Channel!
        if not was_member and is_member:
            logger.info(f"Real-time event: User {user.id} joined channel {channel_id}")
            await manager.on_member_joined(
                bot=bot,
                channel_id=channel_id,
                user_id=user.id,
                user_first_name=user.first_name,
                bot_id=bot.id,
            )

        # 2. User Left / Was Kicked from the Channel!
        elif was_member and not is_member:
            logger.info(f"Real-time event: User {user.id} left channel {channel_id}")
            await manager.on_member_left(
                channel_id=channel_id,
                user_id=user.id,
                bot_id=bot.id,
            )

    return router


def setup_forced_sub_handlers(
    dispatcher_or_router: Union[Dispatcher, Router],
    manager: ForcedSubManager,
) -> Router:
    """
    Convenience helper to register the forced subscription router into a Dispatcher or Router.
    """
    router = create_forced_sub_router(manager)
    dispatcher_or_router.include_router(router)
    return router
