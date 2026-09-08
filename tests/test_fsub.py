import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock

from tg_forced_sub.models import ForcedChannel, ChannelStatus, ChannelType, CheckResult
from tg_forced_sub.manager import ForcedSubManager


class TestForcedSubModels(unittest.TestCase):

    def test_channel_expiration(self):
        # Expired channel
        ch_expired = ForcedChannel(
            channel_id=-1001,
            title="Expired",
            invite_link="https://t.me/exp",
            expire_at=int(time.time()) - 100
        )
        self.assertTrue(ch_expired.is_expired)
        self.assertFalse(ch_expired.is_available)
        self.assertEqual(ch_expired.remaining_ttl, 0)

        # Active future channel
        ch_active = ForcedChannel(
            channel_id=-1002,
            title="Active",
            invite_link="https://t.me/act",
            expire_at=int(time.time()) + 3600
        )
        self.assertFalse(ch_active.is_expired)
        self.assertTrue(ch_active.is_available)
        self.assertGreater(ch_active.remaining_ttl, 3500)

    def test_channel_quota(self):
        ch = ForcedChannel(
            channel_id=-1003,
            title="Quota",
            invite_link="https://t.me/q",
            target_joins=10,
            current_joins=9
        )
        self.assertFalse(ch.is_quota_reached)
        self.assertTrue(ch.is_available)

        ch.current_joins = 10
        self.assertTrue(ch.is_quota_reached)
        self.assertFalse(ch.is_available)


class TestForcedSubManager(unittest.IsolatedAsyncioTestCase):

    async def test_formatting_and_keyboard(self):
        storage_mock = MagicMock()
        manager = ForcedSubManager(
            storage=storage_mock,
            custom_message="Hello {name}! Join {count} channels:\n{channels}",
            check_button_text="Verify Now"
        )

        unjoined = [
            ForcedChannel(channel_id=-1001, title="Channel A", invite_link="https://t.me/ch_a"),
            ForcedChannel(channel_id=-1002, title="Channel B", invite_link="https://t.me/ch_b"),
        ]
        result = CheckResult(
            is_subscribed=False,
            unjoined_channels=unjoined,
            user_id=12345
        )

        formatted = manager.format_message(result, user_first_name="Rabie")
        self.assertIn("Hello Rabie!", formatted)
        self.assertIn("Channel A", formatted)
        self.assertIn("Channel B", formatted)

        kb = manager.build_keyboard(result)
        self.assertEqual(len(kb.inline_keyboard), 3) # 2 channels + 1 verify button
        self.assertEqual(kb.inline_keyboard[0][0].text, "📢 Channel A")
        self.assertEqual(kb.inline_keyboard[0][0].url, "https://t.me/ch_a")
        self.assertEqual(kb.inline_keyboard[2][0].text, "Verify Now")
        self.assertEqual(kb.inline_keyboard[2][0].callback_data, "fsub:check")

    async def test_live_member_join_and_leave(self):
        storage_mock = AsyncMock()
        storage_mock.get_active_prompt.return_value = {"chat_id": 999, "message_id": 888}
        storage_mock.get_channels.return_value = []

        manager = ForcedSubManager(storage=storage_mock)
        bot_mock = AsyncMock()

        # Test on_member_joined
        await manager.on_member_joined(
            bot=bot_mock,
            channel_id=-1001,
            user_id=123,
            user_first_name="Rabie"
        )
        storage_mock.cache_user_subscription.assert_called()
        storage_mock.record_user_join.assert_called()
        bot_mock.edit_message_text.assert_called()

        # Test on_member_left
        await manager.on_member_left(
            channel_id=-1001,
            user_id=123
        )
        storage_mock.invalidate_user_cache.assert_called()


if __name__ == "__main__":
    unittest.main()

