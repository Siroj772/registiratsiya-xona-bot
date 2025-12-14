from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
import sqlite3, os
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ================= CONFIG =================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
PRICE_PER_DAY = 26666
ROOM_LIMIT = 4

# ================= DATABASE =================
conn = sqlite3.connect("data.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room INTEGER,
    name TEXT,
    telegram_id INTEGER,
    telegram_username TEXT,
    passport_photo TEXT,
    date_out TEXT,
    money INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER,
    room INTEGER,
    amount INTEGER,
    created_at TEXT
)
""")
conn.commit()

# ================= HELPERS =================
def set_setting(key, value):
    cursor.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)",
        (key, value)
    )
    conn.commit()

def get_setting(key):
    cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
    r = cursor.fetchone()
    return r[0] if r else None

def calc_new_date(old_date, amount):
    seconds = (amount / PRICE_PER_DAY) * 86400
    base = datetime.now()
    if old_date:
        d = datetime.strptime(old_date, "%Y-%m-%d %H:%M")
        if d > base:
            base = d
    return base + timedelta(seconds=seconds)

def remaining(date_out):
    d = datetime.strptime(date_out, "%Y-%m-%d %H:%M")
    diff = d - datetime.now()
    return diff.days, diff.seconds // 3600

# ================= ROOMS =================
def room_buttons():
    kb = []
    for i in range(1, 25, 2):
        kb.append([
            InlineKeyboardButton(f"Xona {i}", callback_data=f"room_{i}"),
            InlineKeyboardButton(f"Xona {i+1}", callback_data=f"room_{i+1}")
        ])
    kb.append([InlineKeyboardButton("💳 Karta qo‘shish", callback_data="add_card")])
    return InlineKeyboardMarkup(kb)

async def show_rooms(msg):
    await msg.reply_text("🏠 Xonani tanlang:", reply_markup=room_buttons())

async def show_room(msg, room):
    cursor.execute("SELECT id, name, date_out, money FROM people WHERE room=?", (room,))
    rows = cursor.fetchall()

    text = f"🏠 Xona {room}\n\n"
    kb = []
    total = 0

    for pid, name, date_out, money in rows:
        total += money
        until = "—"
        icon = ""
        if date_out:
            until = date_out
            d, _ = remaining(date_out)
            if d <= 3:
                icon = "🔴"
        text += f"👤 {name} — {until} {icon}\n"
        kb.append([InlineKeyboardButton(name, callback_data=f"person_{pid}")])

    text += f"\n📊 Xona balansi: {total:,} so‘m"

    if len(rows) < ROOM_LIMIT:
        kb.append([InlineKeyboardButton("➕ Odam qo‘shish", callback_data="add")])

    kb.append([InlineKeyboardButton("⬅ Orqaga", callback_data="back_rooms")])
    await msg.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))

# ================= SCHEDULER JOBS =================
async def send_total_balance(app):
    cursor.execute("SELECT SUM(amount) FROM payments")
    total = cursor.fetchone()[0] or 0
    await app.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📊 10 KUNLIK HISOBOT\n\n💰 Umumiy tushum:\n{total:,} so‘m"
    )

async def check_expiring(app):
    cursor.execute("""
        SELECT name, telegram_id, date_out FROM people
        WHERE telegram_id IS NOT NULL AND date_out IS NOT NULL
    """)
    for name, tid, date_out in cursor.fetchall():
        days, _ = remaining(date_out)
        if days == 3:
            try:
                await app.bot.send_message(
                    chat_id=tid,
                    text=(
                        "⚠️ Ogohlantirish!\n\n"
                        "⏳ Yashash muddati tugashiga 3 kun qoldi.\n\n"
                        f"📅 Amal qilish muddati:\n{date_out}"
                    )
                )
            except:
                pass

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if update.effective_user.id == ADMIN_ID:
        await show_rooms(update.message)
    else:
        await update.message.reply_text(
            "👋 Xush kelibsiz",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 To‘lov qilish", callback_data="pay")],
                [InlineKeyboardButton("🧾 Mening to‘lovlarim", callback_data="payments_me")]
            ])
        )

# ================= CALLBACKS =================
async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "back_rooms":
        context.user_data.clear()
        await show_rooms(q.message)

    elif q.data.startswith("room_"):
        room = int(q.data.split("_")[1])
        context.user_data.clear()
        context.user_data["room"] = room
        await show_room(q.message, room)

    elif q.data == "add":
        context.user_data["step"] = "name"
        await q.message.reply_text("👤 Ismini yozing:")

    elif q.data == "add_card":
        context.user_data["step"] = "add_card"
        await q.message.reply_text("💳 Karta raqamini yozing:")

    elif q.data == "pay":
        card = get_setting("card") or "❌ Karta kiritilmagan"
        await q.message.reply_text(
            f"💳 To‘lov uchun karta:\n\n{card}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ To‘ladim", callback_data="paid")]
            ])
        )

    elif q.data == "paid":
        context.user_data["step"] = "check"
        await q.message.reply_text("📸 Chekni yuboring")

    elif q.data.startswith("confirm_"):
        uid = int(q.data.split("_")[1])
        context.user_data["step"] = "confirm"
        context.user_data["confirm_uid"] = uid
        await q.message.reply_text("💰 Summani yozing:")

# ================= TEXT =================
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")

    if step == "add_card":
        set_setting("card", update.message.text)
        context.user_data.clear()
        await update.message.reply_text("✅ Karta saqlandi")
        await show_rooms(update.message)

    elif step == "confirm":
        amount = int(update.message.text)
        uid = context.user_data["confirm_uid"]

        cursor.execute("SELECT room, date_out FROM people WHERE telegram_id=?", (uid,))
        room, old = cursor.fetchone()

        new_date = calc_new_date(old, amount)
        new_date_str = new_date.strftime("%Y-%m-%d %H:%M")

        cursor.execute("""
            UPDATE people SET date_out=?, money=money+?
            WHERE telegram_id=?
        """, (new_date_str, amount, uid))
        conn.commit()

        cursor.execute("""
            INSERT INTO payments (telegram_id, room, amount, created_at)
            VALUES (?,?,?,?)
        """, (uid, room, amount, datetime.now().strftime("%Y-%m-%d %H:%M")))
        conn.commit()

        # odamga xabar
        await context.bot.send_message(
            chat_id=uid,
            text=(
                "✅ To‘lovingiz qabul qilindi\n\n"
                f"💰 Summa: {amount:,} so‘m\n"
                f"📅 Amal qilish muddati:\n{new_date_str} gacha"
            )
        )

        context.user_data.clear()
        await update.message.reply_text("✅ To‘lov tasdiqlandi")
        await show_rooms(update.message)

# ================= PHOTO =================
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("step") == "check":
        uid = update.effective_user.id
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=update.message.photo[-1].file_id,
            caption=f"💳 CHEK\nTelegram ID: {uid}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"confirm_{uid}")]
            ])
        )
        context.user_data.clear()
        await update.message.reply_text("⏳ Chek adminga yuborildi")

# ================= MAIN =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_total_balance, "interval", days=10, args=[app])
    scheduler.add_job(check_expiring, "interval", hours=24, args=[app])
    scheduler.start()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))

    app.run_polling()






