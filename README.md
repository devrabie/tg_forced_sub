# 🚀 tg_forced_sub

> حزمة بايثون متطورة وعالية الأداء لإدارة **الاشتراك الإجباري (Forced Subscription)** لبوتات تليجرام (`aiogram 3.x`) معتمدة على **Redis**. مصممة لتكون قابلة لإعادة الاستخدام في أي مشروع فردي أو مصانع البوتات المتعددة (Multi-Bot Factories) بتركيب سهل وسريع (Plug & Play).

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![aiogram 3.x](https://img.shields.io/badge/aiogram-3.x-2ba02c.svg)](https://docs.aiogram.dev/)
[![Redis](https://img.shields.io/badge/redis-asyncio-dc382d.svg)](https://redis.io/)

---

## ✨ أبرز الميزات (Key Features)

1. **⚡ كاش ذكي فائق السرعة عبر Redis**:
   - تجنب حظر تليجرام (`Telegram FloodWait / 429 Too Many Requests`) بفضل تخزين حالة اشتراك المستخدم لفترة محددة (مثل ساعة) وعدم فحص تليجرام في كل رسالة.
   - **Negative Caching (مانع السبام)**: كاش سلبي يمنع إغراق البوت عند ضغط المستخدم المتكرر على زر التحقق.
2. **📢 دعم قنوات طلبات الانضمام (Join Requests Tracking)**:
   - الاستماع التلقائي لطلبات الانضمام (`ChatJoinRequest`) واعتبار المستخدم مشتركاً بمجرد إرسال الطلب (اختياري).
3. **🎯 التدوير الذكي ونظام الحصص (Smart Rotation & Join Quotas)**:
   - **Max Visible Channels**: إمكانية تحديد حد أقصى للقنوات الظاهرة للمستخدم دفعة واحدة (مثلاً قناتين فقط) لمنع تنفيره.
   - **Join Quotas**: إيقاف القناة تلقائياً بمجرد وصولها لعدد المشتركين المستهدف.
4. **⏰ دعم القنوات المؤقتة (Expiration / TTL)**:
   - تحديد وقت انتهاء (بالدقائق أو الساعات أو الأيام) للقنوات الإعلانية والممولة، لتُحذف أو تتوقف تلقائياً بعد انتهاء المدة.
5. **🏢 دعم التعددية لمصانع البوتات (Multi-Tenant Hierarchy)**:
   - دعم القنوات العامة (`global`) المفروضة على جميع البوتات التابعة للمصنع.
   - دعم قنوات خاصة بكل بوت فرعي (`bot_id`) دون أي تداخل في البيانات.
6. **🛡️ التعافي الذاتي (Self-Healing Fallback)**:
   - في حال طرد البوت من قناة أو فقدان صلاحياته، يتم تجاوز القناة مؤقتاً لتجنب تعطيل المستخدمين، مع إمكانية إرسال إشعار للمطور.
7. **🔌 3 طرق تكامل مرنة**:
   - **Middleware**: لحماية البوت بالكامل بسطر واحد.
   - **Filter**: لحماية أوامر أو أقسام معينة فقط (`ForcedSubFilter`).
   - **Manual Call**: استدعاء برمجياً في أي مكان بالكود (`manager.check_user(...)`).

---

## 📦 التثبيت (Installation)

### التثبيت المباشر عبر مستودع GitHub:
```bash
pip install git+https://github.com/devrabie/tg_forced_sub.git
```

### أو التثبيت محلياً بنمط التطوير داخل مسار مشروعك:
```bash
cd tg_forced_sub
pip install -e .
```

---

## 🚀 البدء السريع (Quick Start)

### مثال بسيط مع `aiogram 3.x`:

```python
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from redis.asyncio import Redis

from tg_forced_sub import (
    ForcedSubManager,
    ForcedSubMiddleware,
    setup_forced_sub_handlers
)

BOT_TOKEN = "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
REDIS_URL = "redis://localhost:6379/0"
ADMIN_IDS = [123456789]  # معرفات الأدمن لتخطي الفحص

async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    redis = Redis.from_url(REDIS_URL)

    # 1. تهيئة مدير الاشتراك الإجباري
    manager = ForcedSubManager(
        storage=redis,
        cache_ttl=3600,             # حفظ حالة الاشتراك لمدة ساعة
        negative_cache_ttl=6,       # تهدئة زر التحقق 6 ثوانٍ لمنع السبام
        max_visible_channels=2,     # عرض قناتين كحد أقصى للمستخدم
        allow_pending_requests=True # احتساب طلبات الانضمام
    )

    # إضافة قناة دائمة
    await manager.add_channel(
        channel_id=-1001234567890,
        title="قناتنا الرسمية",
        invite_link="https://t.me/my_channel"
    )

    # إضافة قناة مؤقتة تنتهي بعد 24 ساعة (86400 ثانية) وبحصة 500 مشترك
    await manager.add_channel(
        channel_id=-1009876543210,
        title="قناة الراعي",
        invite_link="https://t.me/sponsor_channel",
        expire_seconds=86400,
        target_joins=500
    )

    # 2. تسجيل معالجات زر التحقق وطلبات الانضمام
    setup_forced_sub_handlers(dp, manager)

    # 3. تفعيل الميدلوير لحماية المحادثات الخاصة
    dp.update.outer_middleware(
        ForcedSubMiddleware(
            manager=manager,
            ignore_admins=ADMIN_IDS,
            ignore_commands=["/help", "/about"]
        )
    )

    # المعالجات العادية للبوت
    @dp.message(CommandStart())
    async def cmd_start(message: types.Message):
        await message.answer(f"أهلاً بك {message.from_user.first_name} في البوت!")

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 🎯 الحماية الجزئية عبر الفلاتر (Using Filters)

إذا كنت ترغب في تشغيل البوت بدون ميدلوير عام، وحماية أوامر أو أقسام معينة فقط (مثل أوامر VIP أو التحميل):

```python
from aiogram.filters import Command
from tg_forced_sub import ForcedSubFilter

@router.message(Command("vip_feature"), ForcedSubFilter(manager))
async def vip_command(message: types.Message):
    await message.answer("مرحباً بك في الميزة الخاصة!")
```

---

## 🏢 استخدام الحزمة في مصانع البوتات (Multi-Bot Factory)

في منصات مثل `BotSane`، يمكنك الفصل التام بين قنوات المطور الأساسية وقنوات كل بوت مصنوع:

```python
# 1. قنوات عامة لمالك المنصة (تفرض على كل البوتات المصنوعة)
await manager.add_channel(
    channel_id=-1001111111111,
    title="قناة المنصة الرسمية",
    invite_link="https://t.me/platform_channel",
    scope="global"
)

# 2. قنوات خاصة بصاحب البوت المصنوع (مثلاً البوت رقم 98765432)
await manager.add_channel(
    channel_id=-1002222222222,
    title="قناة صاحب هذا البوت",
    invite_link="https://t.me/child_bot_channel",
    scope="98765432"  # معرّف البوت الفرعي
)
```

عندما يرسل المستخدم رسالة لأي بوت فرعي، يقوم الميدلوير تلقائياً بفحص:
1. قنوات الـ `global`.
2. قنوات الـ `bot_id` التابع للبوت الحالي.

---

## ⚙️ تخصيص الرسالة والمتغيرات (Template Customization)

يمكنك تخصيص الرسالة التي تظهر للمستخدم باستخدام المتغيرات التالية:
* `{name}`: اسم المستخدم الأول.
* `{user_id}`: الآيدي الخاص بالمستخدم.
* `{channels}`: قائمة القنوات المنسقة مع روابطها.
* `{count}`: عدد القنوات المطلوب الاشتراك فيها.

```python
manager = ForcedSubManager(
    storage=redis,
    custom_message="عزيزي {name}، متبقي {count} قنوات عليك الانضمام إليها:\n\n{channels}\n\nاضغط تحقق بعد الاشتراك.",
    check_button_text="🔍 فحص اشتراكي"
)
```

---

## 🛠️ الدوال البرمجية (API Reference)

### `ForcedSubManager`:
* `add_channel(...)`: إضافة قناة جديدة مع دعم الخصائص المتقدمة (الحصة، تاريخ الانتهاء، الأولوية).
* `remove_channel(channel_id, scope)`: حذف قناة.
* `get_channels(scope, active_only)`: جلب قائمة القنوات.
* `check_user(bot, user_id, user_first_name, bot_id)`: فحص العضوية يدوياً وإرجاع `CheckResult`.
* `format_message(result, user_first_name)`: تجهيز نص الرسالة.
* `build_keyboard(result)`: بناء أزرار القنوات مع زر التحقق.

---

## 📄 الترخيص (License)

هذا المشروع مرخص تحت رخصة **MIT**. يمكنك استخدامه وتعديله بحرية في مشاريعك التجارية والشخصية.
