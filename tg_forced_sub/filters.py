from __future__ import annotations

from typing import Optional, Union
from aiogram import Bot
from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery

from tg_forced_sub.manager import ForcedSubManager


class ForcedSubFilter(BaseFilter):
    """
    aiogram 3.x Filter to protect individual handlers or sub-routers.
    
    Usage:
        @router.message(Command("vip"), ForcedSubFilter(manager))
        async def vip_handler(msg: Message):
            ...
    """

    def __init__(self, manager: ForcedSubManager, send_prompt: bool = True):
        self.manager = manager
        self.send_prompt = send_prompt

    async def __call__(
        self, event: Union[Message, CallbackQuery], bot: Bot
    ) -> bool:
        user = event.from_user
        if not user or user.is_bot:
            return True

        result = await self.manager.check_user(
            bot=bot,
            user_id=user.id,
            user_first_name=user.first_name,
            bot_id=bot.id,
        )

        if result.is_subscribed:
            return True

        if self.send_prompt:
            text = self.manager.format_message(result, user.first_name)
            keyboard = self.manager.build_keyboard(result)

            if isinstance(event, Message):
                await event.answer(
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            elif isinstance(event, CallbackQuery):
                await event.answer("⚠️ عليك الإشتراك بالقنوات أولًا!", show_alert=True)
                if event.message:
                    try:
                        await event.message.edit_text(
                            text=text,
                            reply_markup=keyboard,
                            parse_mode="HTML",
                            disable_web_page_preview=True,
                        )
                    except Exception:
                        pass

        return False
