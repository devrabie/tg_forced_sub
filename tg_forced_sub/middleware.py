from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Optional, Union
from aiogram import BaseMiddleware, Bot
from aiogram.enums import ChatType
from aiogram.types import TelegramObject, Message, CallbackQuery, Update

from tg_forced_sub.manager import ForcedSubManager


class ForcedSubMiddleware(BaseMiddleware):
    """
    aiogram 3.x Middleware to intercept incoming updates and enforce channel subscription.
    Can be attached globally to `dp.update.outer_middleware(...)` or per-router.
    """

    def __init__(
        self,
        manager: ForcedSubManager,
        ignore_admins: Optional[List[int]] = None,
        ignore_commands: Optional[List[str]] = None,
        private_only: bool = True,
        auto_answer_callbacks: bool = True,
    ):
        self.manager = manager
        self.ignore_admins = set(ignore_admins or [])
        self.ignore_commands = set(cmd.lower() for cmd in (ignore_commands or []))
        self.private_only = private_only
        self.auto_answer_callbacks = auto_answer_callbacks

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Extract underlying event if registered at update-level
        real_event = event
        if isinstance(event, Update):
            real_event = event.event

        user = getattr(real_event, "from_user", None)
        if not user or user.is_bot:
            return await handler(event, data)

        # 1. Ignore whitelisted admins
        if user.id in self.ignore_admins:
            return await handler(event, data)

        # 2. Check chat type
        chat = getattr(real_event, "chat", None)
        if self.private_only and chat and chat.type != ChatType.PRIVATE:
            return await handler(event, data)

        # 3. Bypass verification callback
        if isinstance(real_event, CallbackQuery):
            if real_event.data and real_event.data == self.manager.check_callback_data:
                return await handler(event, data)

        # 4. Check whitelisted commands
        if isinstance(real_event, Message) and real_event.text:
            cmd = real_event.text.split()[0].lower()
            if cmd in self.ignore_commands:
                return await handler(event, data)

        # 5. Perform subscription check
        bot: Bot = data.get("bot") or real_event.bot  # type: ignore
        result = await self.manager.check_user(
            bot=bot,
            user_id=user.id,
            user_first_name=user.first_name,
            bot_id=bot.id,
        )

        if result.is_subscribed:
            return await handler(event, data)

        # 6. Not subscribed -> Intercept & Prompt User
        text = self.manager.format_message(result, user.first_name)
        keyboard = self.manager.build_keyboard(result)

        if isinstance(real_event, Message):
            await real_event.answer(
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        elif isinstance(real_event, CallbackQuery):
            if self.auto_answer_callbacks:
                await real_event.answer(
                    "⚠️ عليك الإشتراك بالقنوات أولًا لاستخدام البوت!",
                    show_alert=True,
                )
            if real_event.message:
                try:
                    await real_event.message.edit_text(
                        text=text,
                        reply_markup=keyboard,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                except Exception:
                    pass

        # Stop event from propagating to downstream handlers
        return None
