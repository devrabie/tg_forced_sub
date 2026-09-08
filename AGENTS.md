# 🤖 AGENTS.md — Developer & AI Agent Guide for `tg_forced_sub`

Welcome to **`tg_forced_sub`**! This document serves as the single source of truth for AI coding assistants (Antigravity, Cursor, Windsurf, Copilot, etc.) and human developers integrating or extending this package.

---

## 📌 1. Package Purpose & Philosophy

`tg_forced_sub` is a modular, high-performance **Forced Channel Subscription** framework designed for **`aiogram 3.x`** and powered by **`redis.asyncio`**.

### Key Architectural Pillars:
1. **Zero-Overhead Telegram Calls**: Membership is cached in Redis with a configurable TTL (e.g. 1 hour). Telegram's `getChatMember` API is called only when necessary.
2. **Negative Caching (Anti-Spam)**: Prevents flood attacks by enforcing a cooldown (e.g. 6 seconds) on the verification callback.
3. **Real-time Live UI Updates**: Listens to `ChatMemberUpdated` events. When a user joins a channel in real-time, the bot dynamically edits the warning message—removing the joined channel's button or dismissing the prompt automatically!
4. **Join Requests Tracking**: Listens to `ChatJoinRequest` events and treats pending join requests as satisfied if enabled.
5. **Multi-Tenant Hierarchy**: Supports both `global` channels (platform-wide) and bot-specific channels (`bot_id`) without database or Redis key collisions. Perfect for bot makers like `BotSane`.
6. **Self-Healing Fallback**: If a channel is deleted or the bot loses admin privileges, the channel is marked as degraded (e.g. for 10 minutes) and skipped, preventing user lockouts.

---

## 🏗️ 2. Core Architecture & Component Map

```
┌────────────────────────────────────────────────────────┐
│                   aiogram 3.x Bot                      │
└──────────────────────────┬─────────────────────────────┘
                           │ Incoming Update
                           ▼
┌────────────────────────────────────────────────────────┐
│                 ForcedSubMiddleware                    │
│  - Checks Ignore Admins & Allowed Commands             │
│  - Private chat filtering                              │
│  - Intercepts unjoined users & sends prompt            │
│  - Saves active prompt (chat_id, msg_id) in Redis      │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│                  ForcedSubManager                      │
│  - check_user(bot, user_id, bot_id)                    │
│  - on_member_joined(...) / on_member_left(...)         │
│  - format_message(...) & build_keyboard(...)           │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│             RedisStorage (BaseStorage)                 │
│  - Channels metadata & Sets                            │
│  - Positive membership cache (TTL: 3600s)              │
│  - Negative rate-limit cache (TTL: 6s)                 │
│  - Active prompt coordinates                           │
│  - Unique join counting & quotas                       │
└────────────────────────────────────────────────────────┘
```

---

## 🔑 3. Redis Key Convention Schema

All keys use a configurable prefix (default: `fsub`):

| Key Pattern | Type | Description |
| :--- | :--- | :--- |
| `fsub:{scope}:channels` | `Set` | Set of channel IDs registered for `scope` (`global` or `bot_id`). |
| `fsub:{scope}:channel:{channel_id}` | `String (JSON)` | Serialized `ForcedChannel` model. |
| `fsub:cache:{scope}:{channel_id}:{user_id}` | `String ("1")` | Positive cache indicating user is currently verified (TTL: `cache_ttl`). |
| `fsub:neg_cache:{scope}:{user_id}` | `String ("1")` | Anti-spam lock on the verification button (TTL: `negative_cache_ttl`). |
| `fsub:prompt:{scope}:{user_id}` | `String (JSON)` | Active prompt coordinates `{"chat_id": ..., "message_id": ...}` for live UI updates. |
| `fsub:counted:{scope}:{channel_id}` | `Set` | Set of user IDs who joined through the bot (for unique conversion statistics). |
| `fsub:pending:{channel_id}` | `Set` | Set of user IDs with pending join requests. |
| `fsub:degraded:{channel_id}` | `String ("1")` | Temporary degraded status when bot permissions fail in a channel (TTL: 600s). |

---

## 📋 4. Integration Recipes for AI Agents

### Recipe 1: Single Bot Setup (`aiogram 3.x`)

```python
import asyncio
from aiogram import Bot, Dispatcher
from redis.asyncio import Redis
from tg_forced_sub import (
    ForcedSubManager,
    ForcedSubMiddleware,
    setup_forced_sub_handlers,
)

async def main():
    bot = Bot(token="TOKEN")
    dp = Dispatcher()
    redis = Redis.from_url("redis://localhost:6379/0")

    manager = ForcedSubManager(
        storage=redis,
        cache_ttl=3600,
        negative_cache_ttl=6,
        max_visible_channels=2,     # Rotate if more than 2
        allow_pending_requests=True # Accept pending join requests
    )

    # 1. Setup routers (handles 'Verify' button, join requests, and live membership events)
    setup_forced_sub_handlers(dp, manager)

    # 2. Attach middleware
    dp.update.outer_middleware(
        ForcedSubMiddleware(
            manager=manager,
            ignore_admins=[123456789],
            ignore_commands=["/help"]
        )
    )

    # 3. CRITICAL: Include chat_member and chat_join_request in allowed_updates!
    await dp.start_polling(
        bot,
        allowed_updates=[
            "message",
            "callback_query",
            "chat_member",
            "chat_join_request"
        ]
    )

if __name__ == "__main__":
    asyncio.run(main())
```

### Recipe 2: Multi-Bot Factory (`BotSane` Style with Webhooks)

When dealing with a bot factory (FastAPI + multiple child bots sharing one Dispatcher):

```python
# In your application startup or webhook router:
from tg_forced_sub import ForcedSubManager, ForcedSubMiddleware, setup_forced_sub_handlers

manager = ForcedSubManager(storage=redis_client)

# Register handlers on shared dispatcher once
setup_forced_sub_handlers(dp, manager)
dp.update.outer_middleware(ForcedSubMiddleware(manager=manager))

# Add Global Channels (affects all child bots)
await manager.add_channel(
    channel_id=-1001111111111,
    title="Main Factory Channel",
    invite_link="https://t.me/factory_channel",
    scope="global"
)

# Add Bot-Specific Channels (affects ONLY child bot 98765432)
await manager.add_channel(
    channel_id=-1002222222222,
    title="Owner's Channel",
    invite_link="https://t.me/owner_channel",
    scope="98765432"  # pass child bot ID as string or int
)
```

### Recipe 3: Selective Protection with Filters

If the user wants forced subscription only on specific commands (e.g. VIP commands or download links):

```python
from aiogram.filters import Command
from tg_forced_sub import ForcedSubFilter

@router.message(Command("download"), ForcedSubFilter(manager))
async def download_handler(message: types.Message):
    await message.answer("Here is your download link!")
```

---

## ⚠️ 5. Critical Telegram API Gotchas

When an AI agent modifies code involving `tg_forced_sub`, pay special attention to:

1. **`allowed_updates` in Polling and Webhook**:
   - Telegram Bot API does **NOT** send `chat_member` updates unless explicitly requested!
   - Always ensure `allowed_updates` includes `"chat_member"` and `"chat_join_request"` when setting webhooks or starting polling.
2. **Bot Permissions in Channel**:
   - The bot MUST be added as an **Administrator** in the forced subscription channel.
   - Required permission: `Invite Users via Link` (صلاحية دعوة المستخدمين عبر الرابط).
3. **Channel ID Format**:
   - Telegram Supergroups and Channels always have an integer ID starting with `-100...` (e.g. `-1001234567890`).
4. **Message Not Modified Errors**:
   - When dynamically updating prompt messages, Telegram may return `Bad Request: message is not modified`. `tg_forced_sub` suppresses this safely, but handlers should not throw exceptions on it.

---

## 🧪 6. Testing & Validation

To run the automated test suite:

```bash
cd tg_forced_sub
python -m unittest tests/test_fsub.py
```
