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

# ================= SCHEDULER =================
async def check_expiring(app):
    cursor.execute("SELECT room, name, date_out FROM people")
    for room, name, date_out in cursor.fetchall():
        if days_left(date_out) == 3:
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

async def show_room(query, room, context):
    context.user_data["room"] = room
    cursor.execute("SELECT id, name, date_out, money FROM people WHERE room=?", (room,))
    rows = cursor.fetchall()

    text = f"🏠 Xona {room}\n\n"
    total = 0
    buttons = []

    for pid, name, date_out, money in rows:
        left = days_left(date_out)
        mark = " 🔴" if left <= 3 else ""
        total += money
        text += f"👤 {name}{mark} — ⏳ {left} kun\n"
        buttons.append([InlineKeyboardButton(name, callback_data=f"person_{pid}")])

    text += f"\n📊 Jami: {total} so‘m"

    actions = []
    if len(rows) < ROOM_LIMIT:
        actions.append([InlineKeyboardButton("➕ Odam qo‘shish", callback_data="add")])
    actions.append([InlineKeyboardButton("⬅ Orqaga", callback_data="back")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons + actions))

async def room_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("room_"):
        await show_room(query, int(query.data.split("_")[1]), context)

    elif query.data == "back":
        await query.edit_message_text("🏠 Xonani tanlang:", reply_markup=room_buttons())

    elif query.data == "add":
        context.user_data["step"] = "name"
        await query.edit_message_text("👤 Ismini yozing:")

    elif query.data.startswith("person_"):
        pid = int(query.data.split("_")[1])
        cursor.execute("SELECT name, passport_photo, date_in, date_out, money FROM people WHERE id=?", (pid,))
        name, passport, date_in, date_out, money = cursor.fetchone()
        left = days_left(date_out)

        caption = (
            f"👤 {name}\n"
            f"📅 Kelgan: {date_in}\n"
            f"📅 Ketadi: {date_out}\n"
            f"⏳ Qoldi: {left} kun\n"
            f"💵 Pul: {money} so‘m"
        )

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Tahrirlash", callback_data=f"edit_{pid}")],
            [InlineKeyboardButton("🗑 O‘chirish", callback_data=f"del_{pid}")],
            [InlineKeyboardButton("⬅ Orqaga", callback_data=f"room_{context.user_data.get('room')}")],
        ])

        if passport:
            await query.message.reply_photo(photo=passport, caption=caption, reply_markup=kb)
        else:
            await query.message.reply_text(caption, reply_markup=kb)

    elif query.data.startswith("del_"):
        pid = int(query.data.split("_")[1])
        cursor.execute("DELETE FROM people WHERE id=?", (pid,))
        conn.commit()
        await show_room(query, context.user_data.get("room"), context)

    elif query.data.startswith("edit_"):
        context.user_data["edit_id"] = int(query.data.split("_")[1])
        context.user_data["step"] = "edit_money"
        await query.message.reply_text("💵 Yangi pul miqdorini kiriting:")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")

    if step == "name":
        context.user_data["name"] = update.message.text
        context.user_data["step"] = "passport"
        await update.message.reply_text("🪪 Pasport rasmini yuboring:")

    elif step == "date_out":
        days = int(update.message.text)
        context.user_data["date_out"] = (date.today() + timedelta(days=days)).strftime("%Y-%m-%d")
        context.user_data["step"] = "money"
        await update.message.reply_text("💵 Pul miqdorini kiriting:")

    elif step == "money":
        room = context.user_data.get("room")
        cursor.execute(
            "INSERT INTO people (room, name, passport_photo, date_in, date_out, money) VALUES (?,?,?,?,?,?)",
            (
                room,
                context.user_data.get("name"),
                context.user_data.get("passport"),
                date.today().strftime("%Y-%m-%d"),
                context.user_data.get("date_out"),
                int(update.message.text),
            ),
        )
        conn.commit()
        context.user_data.clear()
        await update.message.reply_text("✅ Odam qo‘shildi")

    elif step == "edit_money":
        cursor.execute(
            "UPDATE people SET money=? WHERE id=?",
            (int(update.message.text), context.user_data.get("edit_id")),
        )
        conn.commit()
        context.user_data.clear()
        await update.message.reply_text("✏️ Ma’lumot yangilandi")

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
    app.add_handler(CallbackQueryHandler(room_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    app.run_polling()
