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
conn.commit()

# ================= SETTINGS =================
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

# ================= TIME =================
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
    rows = []
    for i in range(1, 25, 2):
        rows.append([
            InlineKeyboardButton(f"Xona {i}", callback_data=f"room_{i}"),
            InlineKeyboardButton(f"Xona {i+1}", callback_data=f"room_{i+1}")
        ])
    return InlineKeyboardMarkup(rows)

async def show_rooms(msg):
    await msg.reply_text("🏠 Xonani tanlang:", reply_markup=room_buttons())

async def show_room(msg, room):
    cursor.execute("SELECT id, name, date_out FROM people WHERE room=?", (room,))
    rows = cursor.fetchall()

    text = f"🏠 Xona {room}\n\n"
    kb = []

    for pid, name, date_out in rows:
        icon = ""
        if date_out:
            d, _ = remaining(date_out)
            if d <= 3:
                icon = "🔴"
        text += f"👤 {name} {icon}\n"
        kb.append([InlineKeyboardButton(name, callback_data=f"person_{pid}")])

    if len(rows) < ROOM_LIMIT:
        kb.append([InlineKeyboardButton("➕ Odam qo‘shish", callback_data="add")])

    kb.append([InlineKeyboardButton("⬅ Orqaga", callback_data="back")])
    await msg.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))

# ================= AUTO BIND =================
async def auto_bind(update: Update):
    user = update.effective_user
    if not user.username:
        return
    cursor.execute("""
        UPDATE people SET telegram_id=?
        WHERE telegram_username=? AND (telegram_id IS NULL OR telegram_id=0)
    """, (user.id, f"@{user.username}"))
    conn.commit()

# ================= SCHEDULER =================
async def check_expiring(app):
    cursor.execute("SELECT name, room, date_out, telegram_id FROM people")
    for name, room, date_out, tg in cursor.fetchall():
        if not date_out or not tg:
            continue
        d, _ = remaining(date_out)
        if d == 3:
            await app.bot.send_message(
                chat_id=tg,
                text=f"⚠️ Ogohlantirish!\n👤 {name}\n🏠 Xona {room}\n⏳ 3 kun qoldi"
            )

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await auto_bind(update)
    uid = update.effective_user.id

    if uid == ADMIN_ID:
        await show_rooms(update.message)
    else:
        await update.message.reply_text(
            "👋 Xush kelibsiz",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 To‘lov qilish", callback_data="pay")]
            ])
        )

# ================= CALLBACKS =================
async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "back":
        await show_rooms(q.message)

    elif q.data.startswith("room_"):
        room = int(q.data.split("_")[1])
        context.user_data.clear()
        context.user_data["room"] = room
        await show_room(q.message, room)

    elif q.data == "add":
        context.user_data.clear()
        context.user_data["step"] = "name"
        await q.message.reply_text("👤 Ismini yozing:")

    elif q.data.startswith("person_"):
        pid = int(q.data.split("_")[1])
        cursor.execute("""
            SELECT name, telegram_id, telegram_username, passport_photo, date_out
            FROM people WHERE id=?
        """, (pid,))
        n, tid, tun, photo, d = cursor.fetchone()

        text = f"👤 {n}\n"
        if tid: text += f"🆔 {tid}\n"
        if tun: text += f"👤 {tun}\n"
        if d:
            dd, hh = remaining(d)
            text += f"⏳ {dd} kun {hh} soat\n"

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅ Orqaga", callback_data=f"room_{context.user_data.get('room')}")]
        ])

        if photo:
            await q.message.reply_photo(photo=photo, caption=text, reply_markup=kb)
        else:
            await q.message.reply_text(text, reply_markup=kb)

    elif q.data == "pay":
        card = get_setting("card") or "❌ Karta kiritilmagan"
        await q.message.reply_text(
            f"💳 To‘lov uchun karta:\n\n{card}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ To‘ladim", callback_data="paid")]
            ])
        )

    elif q.data == "paid":
        context.user_data.clear()
        context.user_data["step"] = "check"
        await q.message.reply_text("📸 Chekni yuboring")

    elif q.data == "add_card":
        context.user_data.clear()
        context.user_data["step"] = "add_card"
        await q.message.reply_text("💳 Karta raqamini yozing:")

    elif q.data.startswith("confirm_"):
        uid = int(q.data.split("_")[1])
        context.user_data.clear()
        context.user_data["step"] = "confirm"
        context.user_data["confirm_uid"] = uid
        await q.message.reply_text("💰 To‘langan summani yozing:")

# ================= TEXT =================
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")

    if step == "name":
        context.user_data["name"] = update.message.text
        context.user_data["step"] = "telegram"
        await update.message.reply_text("👤 Telegram username (@ali) yoki ID yozing:")

    elif step == "telegram":
        t = update.message.text.strip()
        if t.startswith("@"):
            context.user_data["telegram_username"] = t
            context.user_data["telegram_id"] = None
        else:
            context.user_data["telegram_id"] = int(t)
            context.user_data["telegram_username"] = None

        context.user_data["step"] = "passport"
        await update.message.reply_text("🪪 Pasport rasmini yuboring:")

    elif step == "add_card":
        set_setting("card", update.message.text)
        context.user_data.clear()
        await update.message.reply_text("✅ Karta saqlandi")

    elif step == "confirm":
        amount = int(update.message.text)
        uid = context.user_data["confirm_uid"]

        cursor.execute("SELECT date_out FROM people WHERE telegram_id=?", (uid,))
        old = cursor.fetchone()[0]

        new_date = calc_new_date(old, amount)

        cursor.execute("""
            UPDATE people SET date_out=?, money=money+?
            WHERE telegram_id=?
        """, (new_date.strftime("%Y-%m-%d %H:%M"), amount, uid))
        conn.commit()

        d, h = remaining(new_date.strftime("%Y-%m-%d %H:%M"))
        context.user_data.clear()
        await update.message.reply_text(f"✅ Tasdiqlandi\n➕ {d} kun {h} soat")

# ================= PHOTO =================
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")

    # PASPORT
    if step == "passport":
        room = context.user_data.get("room")
        if room is None:
            await update.message.reply_text("❌ Xona topilmadi")
            context.user_data.clear()
            return

        cursor.execute("""
            INSERT INTO people
            (room, name, telegram_id, telegram_username, passport_photo)
            VALUES (?,?,?,?,?)
        """, (
            room,
            context.user_data["name"],
            context.user_data.get("telegram_id"),
            context.user_data.get("telegram_username"),
            update.message.photo[-1].file_id
        ))
        conn.commit()

        context.user_data.clear()
        await show_room(update.message, room)

    # CHEK
    elif step == "check":
        uid = update.effective_user.id
        photo = update.message.photo[-1].file_id

        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=photo,
            caption=f"💳 TO‘LOV CHEKI\nTelegram ID: {uid}",
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
    scheduler.add_job(check_expiring, "interval", hours=24, args=[app])
    scheduler.start()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))

    app.run_polling()



