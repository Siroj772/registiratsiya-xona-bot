import os
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ================= CONFIG =================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
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
    telegram_id INTEGER UNIQUE,
    date_out TEXT,
    money INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER,
    amount INTEGER,
    created_at TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS admins (
    telegram_id INTEGER PRIMARY KEY
)
""")
conn.commit()

# ================= ADMIN HELPERS =================
def is_admin(uid: int) -> bool:
    cursor.execute("SELECT 1 FROM admins WHERE telegram_id=?", (uid,))
    return cursor.fetchone() is not None

def add_admin(uid: int):
    cursor.execute(
        "INSERT OR IGNORE INTO admins (telegram_id) VALUES (?)",
        (uid,)
    )
    conn.commit()

# birinchi ishga tushganda — birinchi odam admin bo‘lsin
def ensure_first_admin(uid: int):
    cursor.execute("SELECT COUNT(*) FROM admins")
    if cursor.fetchone()[0] == 0:
        add_admin(uid)

# ================= SETTINGS =================
def set_setting(key, value):
    cursor.execute(
        "INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
        (key, value)
    )
    conn.commit()

def get_setting(key):
    cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
    r = cursor.fetchone()
    return r[0] if r else None

# ================= TIME HELPERS =================
def calc_new_date(old_date, amount):
    base = datetime.now()
    if old_date:
        d = datetime.strptime(old_date, "%Y-%m-%d %H:%M")
        if d > base:
            base = d
    return base + timedelta(days=amount / PRICE_PER_DAY)

def remaining(date_out):
    d = datetime.strptime(date_out, "%Y-%m-%d %H:%M")
    diff = d - datetime.now()
    return diff.days, diff.seconds // 3600

# ================= ADMIN UI =================
def rooms_keyboard():
    kb = []
    for i in range(1, 25, 2):
        kb.append([
            InlineKeyboardButton(f"Xona {i}", callback_data=f"room_{i}"),
            InlineKeyboardButton(f"Xona {i+1}", callback_data=f"room_{i+1}")
        ])
    kb.append([
        InlineKeyboardButton("➕ Admin qo‘shish", callback_data="add_admin"),
        InlineKeyboardButton("💳 Karta qo‘shish", callback_data="add_card")
    ])
    return InlineKeyboardMarkup(kb)

def room_text(room):
    cursor.execute(
        "SELECT name, date_out, money FROM people WHERE room=?",
        (room,)
    )
    rows = cursor.fetchall()

    text = f"🏠 Xona {room}\n\n"
    total = 0
    for name, d, m in rows:
        total += m
        icon = ""
        if d:
            days, _ = remaining(d)
            if days <= 3:
                icon = "🔴"
        text += f"👤 {name} — {d or '-'} {icon}\n"

    text += f"\n📊 Xona balansi: {total:,} so‘m"
    return text

def room_people_buttons(room):
    cursor.execute("SELECT id, name FROM people WHERE room=?", (room,))
    rows = cursor.fetchall()
    return [[InlineKeyboardButton(n, callback_data=f"person_{pid}")] for pid, n in rows]

def can_add(room):
    cursor.execute("SELECT COUNT(*) FROM people WHERE room=?", (room,))
    return cursor.fetchone()[0] < ROOM_LIMIT

def add_person(room, name, telegram_id):
    cursor.execute(
        "INSERT INTO people (room, name, telegram_id) VALUES (?,?,?)",
        (room, name, telegram_id)
    )
    conn.commit()

def person_detail(pid):
    cursor.execute(
        "SELECT name, telegram_id, date_out, money FROM people WHERE id=?",
        (pid,)
    )
    n, tid, d, m = cursor.fetchone()

    text = f"👤 {n}\n🆔 {tid}\n💰 Jami: {m:,} so‘m\n"
    if d:
        days, hours = remaining(d)
        text += f"📅 Tugaydi: {d}\n⏳ {days} kun {hours} soat"
    else:
        text += "📅 Sana belgilanmagan"
    return text
# ================= SCHEDULER =================
def setup_scheduler(app):
    scheduler = AsyncIOScheduler()

    async def remind_users():
        cursor.execute(
            "SELECT telegram_id, date_out FROM people WHERE date_out IS NOT NULL"
        )
        for uid, d in cursor.fetchall():
            days = (datetime.strptime(d, "%Y-%m-%d %H:%M") - datetime.now()).days
            if days == 3:
                await app.bot.send_message(
                    uid,
                    "⚠️ Ogohlantirish!\nYashash muddati tugashiga 3 kun qoldi."
                )

    async def balance_report():
        cursor.execute("SELECT SUM(amount) FROM payments")
        total = cursor.fetchone()[0] or 0
        admins = cursor.execute("SELECT telegram_id FROM admins").fetchall()
        for (aid,) in admins:
            await app.bot.send_message(
                aid,
                f"📊 Oxirgi 10 kunlik umumiy balans:\n{total:,} so‘m"
            )

    scheduler.add_job(remind_users, "interval", hours=24)
    scheduler.add_job(balance_report, "interval", days=10)
    scheduler.start()

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    context.user_data.clear()

    ensure_first_admin(uid)

    if is_admin(uid):
        await update.message.reply_text(
            "🏠 Xonalarni tanlang:",
            reply_markup=rooms_keyboard()
        )
        return

    cursor.execute(
        "SELECT room, date_out FROM people WHERE telegram_id=?",
        (uid,)
    )
    info = cursor.fetchone()

    if not info:
        await update.message.reply_text("❌ Siz ro‘yxatda yo‘qsiz")
        return

    room, date_out = info
    text = f"🏠 Xona {room}\n"
    if date_out:
        text += f"⏳ Tugaydi: {date_out}"

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Pul qo‘shish", callback_data="pay")],
            [InlineKeyboardButton("🧾 To‘lovlarim", callback_data="my_payments")]
        ])
    )

# ================= CALLBACKS =================
async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    # ===== ADMIN PANEL =====
    if q.data.startswith("room_") and is_admin(uid):
        room = int(q.data.split("_")[1])
        context.user_data["room"] = room

        kb = room_people_buttons(room)
        if can_add(room):
            kb.append([InlineKeyboardButton("➕ Odam qo‘shish", callback_data="add_person")])
        kb.append([InlineKeyboardButton("⬅ Orqaga", callback_data="back_rooms")])

        await q.message.reply_text(
            room_text(room),
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif q.data == "back_rooms":
        await q.message.reply_text(
            "🏠 Xonalarni tanlang:",
            reply_markup=rooms_keyboard()
        )

    elif q.data == "add_admin" and is_admin(uid):
        context.user_data["step"] = "add_admin"
        await q.message.reply_text("🆔 Admin qilinadigan USER ID ni yuboring:")

    elif q.data == "add_person" and is_admin(uid):
        context.user_data["step"] = "add_person_name"
        await q.message.reply_text("👤 Ismini kiriting:")

    elif q.data.startswith("person_") and is_admin(uid):
        pid = int(q.data.split("_")[1])
        context.user_data["pid"] = pid

        await q.message.reply_text(
            person_detail(pid),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 Pul qo‘shish", callback_data="admin_add_money")],
                [InlineKeyboardButton("🗑 O‘chirish", callback_data="delete_person")],
                [InlineKeyboardButton("⬅ Orqaga", callback_data=f"room_{context.user_data['room']}")]
            ])
        )

    elif q.data == "delete_person" and is_admin(uid):
        cursor.execute("DELETE FROM people WHERE id=?", (context.user_data["pid"],))
        conn.commit()
        await q.message.reply_text("🗑 O‘chirildi")
        await start(update, context)

    elif q.data == "admin_add_money" and is_admin(uid):
        context.user_data["step"] = "admin_money"
        await q.message.reply_text("💰 Summani kiriting:")

    elif q.data == "add_card" and is_admin(uid):
        context.user_data["step"] = "add_card"
        await q.message.reply_text("💳 Karta raqamini kiriting:")

    # ===== USER =====
    elif q.data == "pay":
        card = get_setting("card") or "❌ Karta kiritilmagan"
        await q.message.reply_text(
            f"💳 To‘lov uchun karta:\n{card}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📸 Chek yuborish", callback_data="send_check")]
            ])
        )

    elif q.data == "send_check":
        context.user_data["step"] = "check"
        await q.message.reply_text("📸 Chekni yuboring:")

    elif q.data == "my_payments":
        cursor.execute(
            "SELECT amount, created_at FROM payments WHERE telegram_id=? ORDER BY id DESC",
            (uid,)
        )
        rows = cursor.fetchall()

        text = "🧾 To‘lovlar tarixi:\n\n"
        for a, t in rows:
            text += f"💰 {a:,} so‘m — {t}\n"

        await q.message.reply_text(text)

# ================= TEXT =================
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")
    uid = update.effective_user.id

    if step == "add_admin" and is_admin(uid):
        add_admin(int(update.message.text))
        context.user_data.clear()
        await update.message.reply_text("✅ Yangi admin qo‘shildi")
        await start(update, context)

    elif step == "add_person_name" and is_admin(uid):
        context.user_data["name"] = update.message.text
        context.user_data["step"] = "add_person_id"
        await update.message.reply_text("🆔 Telegram ID ni kiriting:")

    elif step == "add_person_id" and is_admin(uid):
        add_person(
            context.user_data["room"],
            context.user_data["name"],
            int(update.message.text)
        )
        context.user_data.clear()
        await update.message.reply_text("✅ Odam qo‘shildi")
        await start(update, context)

    elif step == "admin_money" and is_admin(uid):
        amount = int(update.message.text)
        pid = context.user_data["pid"]

        cursor.execute("SELECT telegram_id FROM people WHERE id=?", (pid,))
        tid = cursor.fetchone()[0]

        new_date = calc_new_date(
            cursor.execute(
                "SELECT date_out FROM people WHERE telegram_id=?", (tid,)
            ).fetchone()[0],
            amount
        )

        cursor.execute("""
            UPDATE people
            SET date_out=?, money=money+?
            WHERE telegram_id=?
        """, (new_date.strftime("%Y-%m-%d %H:%M"), amount, tid))

        cursor.execute("""
            INSERT INTO payments (telegram_id, amount, created_at)
            VALUES (?,?,?)
        """, (tid, amount, datetime.now().strftime("%Y-%m-%d %H:%M")))

        conn.commit()

        await context.bot.send_message(
            tid,
            f"✅ To‘lov qabul qilindi\n"
            f"💰 {amount:,} so‘m\n"
            f"📅 Tugaydi: {new_date.strftime('%Y-%m-%d %H:%M')}"
        )

        context.user_data.clear()
        await update.message.reply_text("💰 Hisoblandi")
        await start(update, context)

    elif step == "add_card" and is_admin(uid):
        set_setting("card", update.message.text)
        context.user_data.clear()
        await update.message.reply_text("✅ Karta saqlandi")
        await start(update, context)

# ================= PHOTO =================
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("step") == "check":
        uid = update.effective_user.id

        await context.bot.send_photo(
            chat_id=cursor.execute("SELECT telegram_id FROM admins").fetchone()[0],
            photo=update.message.photo[-1].file_id,
            caption=f"💳 CHEK\nTelegram ID: {uid}"
        )

        context.user_data.clear()
        await update.message.reply_text("⏳ Chek adminga yuborildi")

# ================= MAIN =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    setup_scheduler(app)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))

    app.run_polling()



