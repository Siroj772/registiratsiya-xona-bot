from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import sqlite3
import os
from datetime import datetime, date, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ================= CONFIG =================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
ROOM_LIMIT = 4

# ================= DATABASE =================
conn = sqlite3.connect("data.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room INTEGER,
    name TEXT,
    passport_photo TEXT,
    date_in TEXT,
    date_out TEXT,
    money INTEGER
)
""")
conn.commit()

# ================= HELPERS =================
def days_left(date_out: str) -> int:
    d_out = datetime.strptime(date_out, "%Y-%m-%d").date()
    return (d_out - date.today()).days

# ================= BUTTONS =================
def room_buttons():
    buttons = []
    for i in range(1, 25, 2):
        buttons.append([
            InlineKeyboardButton(f"Xona {i}", callback_data=f"room_{i}"),
            InlineKeyboardButton(f"Xona {i+1}", callback_data=f"room_{i+1}"),
        ])
    return InlineKeyboardMarkup(buttons)

# ================= SCHEDULER JOBS =================
async def check_expiring(app):
    cursor.execute("SELECT room, name, date_out FROM people")
    rows = cursor.fetchall()

    for room, name, date_out in rows:
        left = days_left(date_out)
        if left == 3:
            await app.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"⚠️ Ogohlantirish!\n👤 {name}\n🏠 Xona {room}\n⏳ 3 kun qoldi",
            )

# ================= HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Bu bot faqat admin uchun")
        return

    cursor.execute("SELECT SUM(money) FROM people")
    total = cursor.fetchone()[0] or 0

    await update.message.reply_text(
        f"🏠 Xonani tanlang:\n\n📊 Umumiy balans: {total} so‘m",
        reply_markup=room_buttons(),
    )

async def monthly_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("SELECT room, name, money, date_in FROM people")
    rows = cursor.fetchall()

    month = date.today().strftime("%Y-%m")
    total = 0
    text = f"📊 {month} oylik hisobot\n\n"

    for r in rows:
        if r[3].startswith(month):
            total += r[2]
            text += f"🏠 Xona {r[0]} — {r[1]} — {r[2]} so‘m\n"

    text += f"\n💵 Jami: {total} so‘m"
    await update.message.reply_text(text)

async def room_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("room_"):
        room = int(query.data.split("_")[1])
        context.user_data["room"] = room

        cursor.execute("SELECT id, name, date_out, money FROM people WHERE room=?", (room,))
        rows = cursor.fetchall()

        text = f"🏠 Xona {room}\n\n"
        total = 0

        buttons = []
        for r in rows:
            left = days_left(r[2])
            total += r[3]
            text += f"👤 {r[1]} — ⏳ {left} kun qoldi\n"
            buttons.append([InlineKeyboardButton(r[1], callback_data=f"person_{r[0]}")])

        text += f"\n📊 Jami: {total} so‘m"

        action_buttons = []
        if len(rows) < ROOM_LIMIT:
            action_buttons.append([InlineKeyboardButton("➕ Odam qo‘shish", callback_data="add")])

        action_buttons.append([InlineKeyboardButton("⬅ Orqaga", callback_data="back")])

        keyboard = InlineKeyboardMarkup(buttons + action_buttons)
        await query.edit_message_text(text, reply_markup=keyboard)

    elif query.data == "back":
        await query.edit_message_text("🏠 Xonani tanlang:", reply_markup=room_buttons())

    elif query.data == "add":
        context.user_data["step"] = "name"
        await query.edit_message_text("👤 Ismini yozing:")

    elif query.data.startswith("person_"):
        pid = int(query.data.split("_")[1])
        cursor.execute(
            "SELECT name, passport_photo, date_in, date_out, money FROM people WHERE id=?",
            (pid,),
        )
        p = cursor.fetchone()
        left = days_left(p[3])

        text = (
            f"👤 {p[0]}\n"
            f"📅 Kelgan: {p[2]}\n"
            f"📅 Ketadi: {p[3]}\n"
            f"⏳ Qoldi: {left} kun\n"
            f"💵 Pul: {p[4]} so‘m"
        )

        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Orqaga", callback_data=f"room_{context.user_data.get('room')}")]])
        await query.edit_message_text(text, reply_markup=kb)

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")

    if step == "name":
        context.user_data["name"] = update.message.text
        context.user_data["step"] = "passport"
        await update.message.reply_text("🪪 Pasport rasmini yuboring:")

    elif step == "date_out":
        days = int(update.message.text)
        date_out = (date.today() + timedelta(days=days)).strftime("%Y-%m-%d")
        context.user_data["date_out"] = date_out
        context.user_data["step"] = "money"
        await update.message.reply_text(f"📅 Ketish sanasi: {date_out}\n💵 Pul miqdori:")

    elif step == "money":
        room = context.user_data.get("room")
        name = context.user_data.get("name")
        passport = context.user_data.get("passport")
        date_out = context.user_data.get("date_out")
        money = int(update.message.text)
        date_in = date.today().strftime("%Y-%m-%d")

        cursor.execute(
            "INSERT INTO people (room, name, passport_photo, date_in, date_out, money) VALUES (?,?,?,?,?,?)",
            (room, name, passport, date_in, date_out, money),
        )
        conn.commit()

        context.user_data.clear()
        # odam qo‘shilgach xonaga avtomatik qaytamiz
        room = context.user_data.get("room")
        cursor.execute("SELECT id, name, date_out, money FROM people WHERE room=?", (room,))
        rows = cursor.fetchall()

        text = f"🏠 Xona {room}\n\n"
        total = 0
        buttons = []
        for r in rows:
            left = days_left(r[2])
            total += r[3]
            text += f"👤 {r[1]} — ⏳ {left} kun qoldi\n"
            buttons.append([InlineKeyboardButton(r[1], callback_data=f"person_{r[0]}")])

        text += f"\n📊 Jami: {total} so‘m"

        action_buttons = []
        if len(rows) < ROOM_LIMIT:
            action_buttons.append([InlineKeyboardButton("➕ Odam qo‘shish", callback_data="add")])
        action_buttons.append([InlineKeyboardButton("⬅ Orqaga", callback_data="back")])

        keyboard = InlineKeyboardMarkup(buttons + action_buttons)
        context.user_data.clear()
        await update.message.reply_text(text, reply_markup=keyboard)

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("step") == "passport":
        context.user_data["passport"] = update.message.photo[-1].file_id
        context.user_data["step"] = "date_out"
        await update.message.reply_text("📆 Necha kunga qoladi? (masalan: 30)")

# ================= MAIN =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_expiring, "interval", days=1, args=[app])
    scheduler.start()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("hisobot", monthly_report))
    app.add_handler(CallbackQueryHandler(room_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    app.run_polling()
