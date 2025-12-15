import os, sqlite3, requests
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ================= CONFIG =================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ESKIZ_TOKEN = os.environ.get("ESKIZ_TOKEN")
PRICE_PER_DAY = 26666
ROOM_LIMIT = 4

# ================= DATABASE =================
conn = sqlite3.connect("data.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS people(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 room INTEGER,
 name TEXT,
 telegram_id INTEGER UNIQUE,
 phone TEXT,
 passport_photo TEXT,
 date_out TEXT,
 money INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS payments(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 telegram_id INTEGER,
 amount INTEGER,
 created_at TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS admins(
 telegram_id INTEGER PRIMARY KEY
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS settings(
 key TEXT PRIMARY KEY,
 value TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS sms_log(
 telegram_id INTEGER,
 days_left INTEGER,
 sent_at TEXT,
 UNIQUE(telegram_id, days_left)
)
""")
conn.commit()

# ================= HELPERS =================
def is_admin(uid):
    cursor.execute("SELECT 1 FROM admins WHERE telegram_id=?", (uid,))
    return cursor.fetchone() is not None

def ensure_admin(uid):
    cursor.execute("SELECT COUNT(*) FROM admins")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO admins VALUES(?)", (uid,))
        conn.commit()

def set_setting(k, v):
    cursor.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, v))
    conn.commit()

def get_setting(k):
    cursor.execute("SELECT value FROM settings WHERE key=?", (k,))
    r = cursor.fetchone()
    return r[0] if r else None

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

# ================= SMS =================
def send_sms(phone, text):
    if not ESKIZ_TOKEN:
        return
    requests.post(
        "https://notify.eskiz.uz/api/message/sms/send",
        headers={"Authorization": f"Bearer {ESKIZ_TOKEN}"},
        data={"mobile_phone": phone, "message": text, "from": "4546"}
    )

# ================= UI =================
def rooms_kb():
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

def room_view(room):
    cursor.execute("SELECT id,name,date_out FROM people WHERE room=?", (room,))
    rows = cursor.fetchall()
    text = f"🏠 Xona {room}\n\n"
    kb = []
    for pid, n, d in rows:
        icon = ""
        if d:
            days, _ = remaining(d)
            if days <= 2:
                icon = "🔴"
        text += f"👤 {n} {icon}\n"
        kb.append([InlineKeyboardButton(n, callback_data=f"person_{pid}")])
    if len(rows) < ROOM_LIMIT:
        kb.append([InlineKeyboardButton("➕ Odam qo‘shish", callback_data="add_person")])
    kb.append([InlineKeyboardButton("⬅ Orqaga", callback_data="back_rooms")])
    return text, InlineKeyboardMarkup(kb)

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_admin(uid)
    context.user_data.clear()

    if is_admin(uid):
        await update.message.reply_text("🏠 Xonalar:", reply_markup=rooms_kb())
    else:
        await update.message.reply_text(
            "💳 To‘lov",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Pul qo‘shish", callback_data="pay")]
            ])
        )

# ================= CALLBACKS =================
async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if q.data == "back_rooms":
        context.user_data.clear()
        await q.message.edit_text("🏠 Xonalar:", reply_markup=rooms_kb())

    elif q.data.startswith("room_"):
        room = int(q.data.split("_")[1])
        context.user_data["room"] = room
        text, kb = room_view(room)
        await q.message.edit_text(text, reply_markup=kb)

    elif q.data == "add_admin":
        context.user_data["step"] = "add_admin"
        await q.message.edit_text("🆔 Admin ID yozing:")

    elif q.data == "add_card":
        context.user_data["step"] = "add_card"
        await q.message.edit_text("💳 Karta raqamini yozing:")

    elif q.data == "add_person":
        context.user_data["step"] = "name"
        await q.message.edit_text("👤 Ism yozing:")

    elif q.data.startswith("person_"):
        pid = int(q.data.split("_")[1])
        context.user_data["pid"] = pid
        cursor.execute("""
        SELECT name,telegram_id,passport_photo,date_out,money
        FROM people WHERE id=?""", (pid,))
        n, tid, p, d, m = cursor.fetchone()
        text = f"👤 {n}\n🆔 {tid}\n💰 {m:,} so‘m\n📅 {d or '-'}"
        kb = [
            [InlineKeyboardButton("💰 Pul qo‘shish", callback_data="admin_money")],
            [InlineKeyboardButton("🗑 O‘chirish", callback_data="delete_person")],
            [InlineKeyboardButton("⬅ Orqaga", callback_data=f"room_{context.user_data['room']}")]
        ]
        if p:
            await q.message.reply_photo(p, caption=text, reply_markup=InlineKeyboardMarkup(kb))
        else:
            await q.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb))

    elif q.data == "delete_person":
        cursor.execute("DELETE FROM people WHERE id=?", (context.user_data["pid"],))
        conn.commit()
        text, kb = room_view(context.user_data["room"])
        await q.message.edit_text(text, reply_markup=kb)

    elif q.data == "admin_money":
        context.user_data["step"] = "admin_money"
        await q.message.edit_text("💰 Summani yozing:")

    elif q.data == "pay":
        card = get_setting("card") or "❌ Karta yo‘q"
        context.user_data["step"] = "check"
        await q.message.edit_text(
            f"💳 To‘lov uchun karta:\n{card}\n\n📸 Chek yuboring"
        )

# ================= CONFIRM (ADMIN) =================
async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = int(q.data.split("_")[1])
    context.user_data.clear()
    context.user_data["pay_uid"] = uid
    context.user_data["step"] = "confirm_amount"

    await q.message.edit_text("💰 Summani yozing:")

# ================= TEXT =================
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")

    if step == "confirm_amount":
            elif step == "name":
        # ismni saqlaymiz
        context.user_data["name"] = update.message.text
        context.user_data["step"] = "tid"
        await update.message.reply_text("🆔 Telegram ID yozing:")

    elif step == "tid":
        context.user_data["telegram_id"] = int(update.message.text)
        context.user_data["step"] = "phone"
        await update.message.reply_text("📞 Telefon raqam yozing:")

    elif step == "phone":
        context.user_data["phone"] = update.message.text
        context.user_data["step"] = "passport"
        await update.message.reply_text("🪪 Pasport rasmini yuboring:")

        amount = int(update.message.text)
        uid = context.user_data["pay_uid"]

        cursor.execute("SELECT room, date_out FROM people WHERE telegram_id=?", (uid,))
        room, old = cursor.fetchone()

        new = calc_new_date(old, amount)

        cursor.execute("""
        UPDATE people SET date_out=?, money=money+?
        WHERE telegram_id=?
        """, (new.strftime("%Y-%m-%d %H:%M"), amount, uid))

        cursor.execute("""
        INSERT INTO payments VALUES(NULL,?,?,?)
        """, (uid, amount, datetime.now().strftime("%Y-%m-%d %H:%M")))
        conn.commit()

        await context.bot.send_message(
            uid,
            f"✅ To‘lov qabul qilindi\n"
            f"💰 Qo‘shildi: {amount:,} so‘m\n"
            f"📅 Tugaydi: {new.strftime('%Y-%m-%d %H:%M')}"
        )

        context.user_data.clear()
        text, kb = room_view(room)
        await update.message.reply_text("✅ To‘lov tasdiqlandi")
        await update.message.reply_text(text, reply_markup=kb)

# ================= PHOTO =================
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("step") == "check":
        admin = cursor.execute("SELECT telegram_id FROM admins LIMIT 1").fetchone()[0]
        await context.bot.send_photo(
            admin,
            update.message.photo[-1].file_id,
            caption=f"💳 CHEK\nID: {update.effective_user.id}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Tasdiqlash",
                 callback_data=f"confirm_{update.effective_user.id}")]
            ])
        )
        context.user_data.clear()
        await update.message.reply_text("⏳ Chek yuborildi")

# ================= MAIN =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(confirm, pattern="^confirm_"))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))

    app.run_polling()

