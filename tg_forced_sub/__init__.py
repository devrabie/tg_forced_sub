"""
tg_forced_sub: A modular, high-performance Telegram Forced Subscription package for aiogram 3.x.
"""

from tg_forced_sub.models import (
    ForcedChannel,
    ChannelStatus,
    ChannelType,
    ChannelCategory,
    CheckResult,
)
from tg_forced_sub.storage import (
    BaseStorage,
    RedisStorage,
)
from tg_forced_sub.manager import (
    ForcedSubManager,
    DEFAULT_FORCED_SUB_TEMPLATE,
)
from tg_forced_sub.middleware import ForcedSubMiddleware
from tg_forced_sub.filters import ForcedSubFilter
from tg_forced_sub.handlers import (
    create_forced_sub_router,
    setup_forced_sub_handlers,
)

__version__ = "0.1.0"

__all__ = [
    "ForcedChannel",
    "ChannelStatus",
    "ChannelType",
    "ChannelCategory",
    "CheckResult",
    "BaseStorage",
    "RedisStorage",
    "ForcedSubManager",
    "DEFAULT_FORCED_SUB_TEMPLATE",
    "ForcedSubMiddleware",
    "ForcedSubFilter",
    "create_forced_sub_router",
    "setup_forced_sub_handlers",
]
