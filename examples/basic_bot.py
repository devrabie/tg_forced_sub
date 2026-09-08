"""
Example: Basic Telegram Bot using tg_forced_sub with aiogram 3.x
"""

import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from redis.asyncio import Redis

from tg_forced_sub import (
    ForcedSubManager,
    ForcedSubMiddleware,
    setup_forced_sub_handlers,
    ForcedSubFilter,
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
REDIS_URL = "redis://localhost:6379/0"
ADMIN_IDS = [123456789]  # Replace with your Telegram User ID


async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    # 1. Initialize Redis connection
    redis = Redis.from_url(REDIS_URL)

    # 2. Initialize ForcedSubManager
    manager = ForcedSubManager(
        storage=redis,
        cache_ttl=3600,             # Cache membership for 1 hour to save API calls
        negative_cache_ttl=6,       # 6s anti-spam cooldown on check button
        max_visible_channels=2,     # Show at most 2 channels at a time (smart rotation)
        allow_pending_requests=True # Join requests count as joined
    )

    # Add a permanent channel for testing
    await manager.add_channel(
        channel_id=-1001234567890,
        title="قناتنا الرسمية",
        invite_link="https://t.me/example_channel",
        scope="global"
    )

    # Add an expiring sponsored channel (e.g. expires in 24h = 86400s) with 500 join quota
    await manager.add_channel(
        channel_id=-1009876543210,
        title="قناة الراعي الرسمي",
        invite_link="https://t.me/sponsor_channel",
        scope="global",
        expire_seconds=86400,
        target_joins=500
    )

    # 3. Setup forced sub handlers (handles the 'Check' button and Join Requests)
    setup_forced_sub_handlers(dp, manager)

    # 4. Attach Middleware to protect private chats
    dp.update.outer_middleware(
        ForcedSubMiddleware(
            manager=manager,
            ignore_admins=ADMIN_IDS,
            ignore_commands=["/help", "/about"],
            private_only=True
        )
    )

    # 5. Normal bot handlers
    @dp.message(CommandStart())
    async def cmd_start(message: types.Message):
        await message.answer(f"أهلاً بك {message.from_user.first_name}! لقد تم التحقق من اشتراكك بنجاح.")

    @dp.message(Command("help"))
    async def cmd_help(message: types.Message):
        await message.answer("قائمة المساعدة (متاحة للجميع حتى بدون اشتراك إجباري).")

    # 6. Start polling
    print("Bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
