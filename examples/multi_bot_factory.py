"""
Example: Multi-Bot Factory Architecture (like BotSane) with tg_forced_sub.
Shows how global channels (developer-wide) and local channels (child-bot specific)
co-exist seamlessly without database collision.
"""

import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from redis.asyncio import Redis

from tg_forced_sub import (
    ForcedSubManager,
    ForcedSubMiddleware,
    setup_forced_sub_handlers,
)

logging.basicConfig(level=logging.INFO)

REDIS_URL = "redis://localhost:6379/0"
DEVELOPER_ADMIN_ID = 123456789


async def main():
    redis = Redis.from_url(REDIS_URL)

    manager = ForcedSubManager(
        storage=redis,
        cache_ttl=3600,
        allow_pending_requests=True
    )

    # 1. Developer sets GLOBAL channels (enforced on ALL child bots created by the factory)
    await manager.add_channel(
        channel_id=-1001111111111,
        title="قناة مصنع البوتات الرسمية",
        invite_link="https://t.me/factory_official",
        scope="global"
    )

    # 2. Suppose a user created a child bot with ID 99887766
    CHILD_BOT_ID = 99887766

    # The owner of child bot 99887766 adds their OWN forced subscription channel
    await manager.add_channel(
        channel_id=-1002222222222,
        title="قناة صاحب البوت المصنوع",
        invite_link="https://t.me/child_bot_channel",
        scope=str(CHILD_BOT_ID)
    )

    # In your dispatcher (shared or per-bot webhook):
    dp = Dispatcher()
    setup_forced_sub_handlers(dp, manager)
    dp.update.outer_middleware(
        ForcedSubMiddleware(
            manager=manager,
            ignore_admins=[DEVELOPER_ADMIN_ID]
        )
    )

    print("Multi-bot factory forced subscription configured successfully!")
    print(f"Global channels: {await manager.get_channels('global')}")
    print(f"Child bot channels: {await manager.get_channels(str(CHILD_BOT_ID))}")


if __name__ == "__main__":
    asyncio.run(main())
