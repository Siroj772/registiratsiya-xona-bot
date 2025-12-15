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
    passport_photo TEXT,
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

# ================= ADMIN =================
def is_admin(uid):
    cursor.execute("SELECT 1 FROM admins WHERE telegram_id=?", (uid,))
    return cursor.fetchone() is not None

def add_admin(uid):
    cursor.execute("INSERT OR IGNORE INTO admins VALUES (?)", (uid,))
    conn.commit()

def ensure_first_admin(uid):
    cursor.execute("SELECT COUNT(*) FROM admins")
    if cursor.fetchone()[0] == 0:
        add_admin(uid)

# ================= SETTINGS =================
def set_setting(k, v):
    cursor.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (k, v))
    conn.commit()

def get_setting(k):
    cursor.execute("SELECT value FROM settings WHERE key=?", (k,))
    r = cursor.fetchone()
    return r[0] if r else None

# ================= TIME =================
def calc_new_date(old, amount):
    base = datetime.now()
    if old:
        d = datetime.strptime(old, "%Y-%m-%d %H:%M")
        if d > base:
            base = d
    return base + timedelta(days=amount / PRICE_PER_DAY)

def remaining(d):
    diff = datetime.strptime(d, "%Y-%m-%d %H:%M") - datetime.now()
    return diff.days, diff.seconds // 3600

# ================= UI =================
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
    cursor.execute("SELECT name, date_out, money FROM people WHERE room=?", (room,))
    rows = cursor.fetchall()
    text = f"🏠 Xona {room}\n\n"
    total = 0
    for n, d, m in rows:
        total += m
        icon = ""
        if d:
            days, _ = remaining(d)
            if days <= 2:
                icon = "🔴"
        text += f"👤 {n} — {d or '-'} {icon}\n"
    text += f"\n📊 Xona balansi: {total:,} so‘m"
    return text

def room_people(room):
    cursor.execute("SELECT id, name FROM people WHERE room=?", (room,))
    return [[InlineKeyboardButton(n, callback_data=f"person_{i}")] for i, n in cursor.fetchall()]

def person_detail(pid):
    cursor.execute("""
        SELECT name, telegram_id, date_out, money, passport_photo
        FROM people WHERE id=?
    """, (pid,))
    n, tid, d, m, p = cursor.fetchone()

    text = f"👤 {n}\n🆔 {tid}\n💰 {m:,} so‘m\n"
    if d:
        days, h = remaining(d)
        warn = " 🔴" if days <= 2 else ""
        text += f"📅 {d}\n⏳ {days} kun {h} soat{warn}"
    else:
        text += "📅 Sana belgilanmagan"

    return text, p
# ================= SCHEDULER =================
def setup_scheduler(app):
    sch = AsyncIOScheduler()

    async def remind():
        cursor.execute("SELECT telegram_id, date_out FROM people WHERE date_out IS NOT NULL")
        for uid, d in cursor.fetchall():
            if (datetime.strptime(d, "%Y-%m-%d %H:%M") - datetime.now()).days == 3:
                await app.bot.send_message(uid, "⚠️ Ogohlantirish! 3 kun qoldi")

    sch.add_job(remind, "interval", hours=24)
    sch.start()

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    context.user_data.clear()
    ensure_first_admin(uid)

    if is_admin(uid):
        await update.message.reply_text("🏠 Xonalar:", reply_markup=rooms_keyboard())
        return

    cursor.execute("SELECT room, date_out FROM people WHERE telegram_id=?", (uid,))
    r = cursor.fetchone()
    if not r:
        await update.message.reply_text("❌ Siz ro‘yxatda yo‘qsiz")
        return

    await update.message.reply_text(
        f"🏠 Xona {r[0]}\n⏳ {r[1]}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Pul qo‘shish", callback_data="pay")]
        ])
    )

# ================= CALLBACKS =================
async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if q.data.startswith("room_") and is_admin(uid):
        room = int(q.data.split("_")[1])
        context.user_data["room"] = room
        kb = room_people(room)
        if len(kb) < ROOM_LIMIT:
            kb.append([InlineKeyboardButton("➕ Odam qo‘shish", callback_data="add_person")])
        kb.append([InlineKeyboardButton("⬅ Orqaga", callback_data="back")])
        await q.message.reply_text(room_text(room), reply_markup=InlineKeyboardMarkup(kb))

    elif q.data == "add_person":
        context.user_data["step"] = "name"
        await q.message.reply_text("👤 Ismni yozing:")

    elif q.data.startswith("person_"):
        pid = int(q.data.split("_")[1])
        context.user_data["pid"] = pid
        text, photo = person_detail(pid)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Pul qo‘shish", callback_data="admin_money")],
            [InlineKeyboardButton("⬅ Orqaga", callback_data=f"room_{context.user_data['room']}")]
        ])
        if photo:
            await q.message.reply_photo(photo, caption=text, reply_markup=kb)
        else:
            await q.message.reply_text(text, reply_markup=kb)

    elif q.data == "pay":
        context.user_data["step"] = "check"
        await q.message.reply_text("📸 Chekni yuboring")

    elif q.data.startswith("confirm_pay_"):
        context.user_data["pay_uid"] = int(q.data.split("_")[2])
        context.user_data["step"] = "confirm_amount"
        await q.message.reply_text("💰 Summani yozing:")

# ================= TEXT =================
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")

    if step == "name":
        context.user_data["name"] = update.message.text
        context.user_data["step"] = "tid"
        await update.message.reply_text("🆔 Telegram ID:")

    elif step == "tid":
        context.user_data["telegram_id"] = int(update.message.text)
        context.user_data["step"] = "passport"
        await update.message.reply_text("🪪 Pasport rasmini yuboring")

    elif step == "confirm_amount":
        amount = int(update.message.text)
        uid = context.user_data["pay_uid"]
        cursor.execute("SELECT date_out FROM people WHERE telegram_id=?", (uid,))
        old = cursor.fetchone()[0]
        new = calc_new_date(old, amount)

        cursor.execute(
            "UPDATE people SET date_out=?, money=money+? WHERE telegram_id=?",
            (new.strftime("%Y-%m-%d %H:%M"), amount, uid)
        )
        cursor.execute(
            "INSERT INTO payments VALUES (NULL,?,?,?)",
            (uid, amount, datetime.now().strftime("%Y-%m-%d %H:%M"))
        )
        conn.commit()

        await context.bot.send_message(
            uid,
            f"✅ To‘lov qabul qilindi\n💰 {amount:,} so‘m\n📅 {new}"
        )
        context.user_data.clear()

# ================= PHOTO =================
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")

    if step == "passport":
        cursor.execute(
            "INSERT INTO people (room,name,telegram_id,passport_photo) VALUES (?,?,?,?)",
            (context.user_data["room"], context.user_data["name"],
             context.user_data["telegram_id"], update.message.photo[-1].file_id)
        )
        conn.commit()
        context.user_data.clear()
        await update.message.reply_text("✅ Odam qo‘shildi")

    elif step == "check":
        uid = update.effective_user.id
        admin = cursor.execute("SELECT telegram_id FROM admins LIMIT 1").fetchone()[0]
        await context.bot.send_photo(
            admin,
            update.message.photo[-1].file_id,
            caption=f"💳 CHEK\nTelegram ID: {uid}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"confirm_pay_{uid}")]
            ])
        )
        context.user_data.clear()
        await update.message.reply_text("⏳ Chek yuborildi")

# ================= MAIN =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    setup_scheduler(app)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.run_polling()


