import asyncio
import aiosqlite
from datetime import datetime, timedelta
import jdatetime
from rubpy.bot import BotClient, filters
from rubpy.bot.models import Update
from ancient import AncientScripts,AncientTimeline,AncientScriptAI

DB_PATH = "users.db"
REQUEST_LIMIT_SECONDS = 5
api_key=""
class AncientBot:
    def __init__(self, token: str):
        self.bot = BotClient(token=token)
        self.db: aiosqlite.Connection | None = None
        self.converter = AncientScripts()
        self.timeline = AncientTimeline()
        self.ai = AncientScriptAI(api_key=api_key)
        

    async def init_db(self):
        self.db = await aiosqlite.connect(DB_PATH)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id TEXT PRIMARY KEY,
                request_count INTEGER DEFAULT 0,
                last_start TEXT,
                last_request TEXT
            )
        """)
        await self.db.commit()

    async def register_user(self, chat_id: str):
        now = datetime.utcnow().isoformat()
        await self.db.execute("""
            INSERT INTO users(chat_id, request_count, last_start)
            VALUES(?, 0, ?)
            ON CONFLICT(chat_id) DO UPDATE SET last_start = ?
        """, (chat_id, now, now))
        await self.db.commit()

    async def can_request(self, chat_id: str) -> bool:
        cursor = await self.db.execute("SELECT last_request FROM users WHERE chat_id=?", (chat_id,))
        row = await cursor.fetchone()
        now = datetime.utcnow()
        if row and row[0]:
            last = datetime.fromisoformat(row[0])
            if (now - last) < timedelta(seconds=REQUEST_LIMIT_SECONDS):
                return False
        await self.db.execute("UPDATE users SET last_request=? WHERE chat_id=?", (now.isoformat(), chat_id))
        await self.db.commit()
        return True

    async def increment_request(self, chat_id: str):
        await self.db.execute("""
            INSERT INTO users(chat_id, request_count) VALUES(?, 1)
            ON CONFLICT(chat_id) DO UPDATE SET request_count = request_count + 1
        """, (chat_id,))
        await self.db.commit()

    async def get_stats(self, chat_id: str):
        cursor = await self.db.execute("SELECT COUNT(*), SUM(request_count) FROM users")
        total_users, total_requests = await cursor.fetchone()

        cursor = await self.db.execute("SELECT request_count, last_start FROM users WHERE chat_id=?", (chat_id,))
        row = await cursor.fetchone()
        user_count = row[0] if row else 0
        last_start = row[1] if row else None

        return {
            "total_users": total_users,
            "total_requests": total_requests or 0,
            "user_requests": user_count,
            "last_start": last_start
        }

    def register_handlers(self):
        @self.bot.on_update(filters.commands(["start", "help"]))
        async def start_handler(client, msg: Update):
            chat_id = msg.chat_id
            await self.register_user(chat_id)
            stats = await self.get_stats(chat_id)
            last_start_j = jdatetime.datetime.fromisoformat(stats['last_start']).strftime("%Y/%m/%d %H:%M") if stats['last_start'] else "نامشخص"

            await msg.reply(
                f"تاریخ زمان :\n{self.timeline.as_text()}"
                f"سلام! 👋\n"
                f"به ربات تبدیل متن به خطوط باستانی خوش اومدی.\n\n"
                f"📊 آمار شما:\n"
                f"▫️ تعداد درخواست‌ها: {stats['user_requests']}\n"
                f"▫️ آخرین استارت: {last_start_j}\n\n"
                f"⚠️ لطفاً هر {REQUEST_LIMIT_SECONDS} ثانیه فقط یک پیام ارسال کن."
            )

        @self.bot.on_update(filters.commands(["امار", "stats"]))
        async def stats_handler(client, msg: Update):
            chat_id = msg.chat_id
            stats = await self.get_stats(chat_id)
            last_j = jdatetime.datetime.fromisoformat(stats['last_start']).strftime("%Y/%m/%d %H:%M") if stats['last_start'] else "نامشخص"
            await msg.reply(
                f"📊 آمار کلی:\n"
                f"👥 کاربران: {stats['total_users']}\n"
                f"📨 کل درخواست‌ها: {stats['total_requests']}\n\n"
                f"👤 شما:\n"
                f"▫️ درخواست‌ها: {stats['user_requests']}\n"
                f"▫️ آخرین استارت: {last_j}"
            )

        
        @self.bot.on_update(filters.text)
        async def main_text_handler(client, msg: Update):

            if not msg.new_message.text:
                return

            chat_id = msg.chat_id
            text = msg.new_message.text.strip()

          
            if text.startswith("+"):
                prompt = text[1:].strip()

                if not prompt:
                    return await msg.reply("⚠️ بعد از + متن بنویس")

                processing = await msg.reply("⏳ در حال پردازش با هوش مصنوعی...")

                try:
                    res = self.ai.get_ancient_response(prompt, "pahlavi")
                    await processing.edit_text(res)
                except Exception as e:
                    await processing.edit_text("❌ خطا در پاسخ هوش مصنوعی")
                return

            
            if not await self.can_request(chat_id):
                return await msg.reply("⏳ لطفاً چند ثانیه صبر کنید.")

            await self.increment_request(chat_id)
            await msg.reply("⏳ در حال تبدیل متن...")

            scripts = {
                "📜 پهلوی": self.converter.pahlavi,
                "🔶 میخی": self.converter.cuneiform,
                "☀️ مانوی": self.converter.manichaean,
                "𓃭 هیروگلیف": self.converter.hieroglyph,
                "✡️ عبری": self.converter.hebrew,
                "🅱️ خط B": self.converter.linear_b,
                "🕉 سانسکریت": self.converter.sanskrit,
                "⚔️ اکدی": self.converter.akkadian,
                "🦴 اوراکل": self.converter.oracle_bone,
                "براهمی": self.converter.brahmi,
                "اوستایی": self.converter.avestan
            }

            results = []
            for name, func in scripts.items():
                try:
                    results.append(f"{name}:\n{func(text)}")
                except:
                    results.append(f"{name}:\n❌ خطا")

            payload = "\n\n".join(results)

            for i in range(0, len(payload), 4000):
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=payload[i:i+4000],
                    reply_to_message_id=msg.new_message.message_id
                )
                await asyncio.sleep(0.3)


            
         

    async def run(self):
        await self.init_db()
        self.register_handlers()
        await self.bot.run()

if __name__ == "__main__":
    bot = AncientBot(token="")
    asyncio.run(bot.run())
