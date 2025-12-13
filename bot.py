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

# ================= UI =================
async def show_rooms(message):
    cursor.execute("SELECT SUM(money) FROM people")
    total = cursor.fetchone()[0] or 0
    await message.reply_text(
        f"🏠 Xonani tanlang:\n\n📊 Umumiy balans: {total} so‘m",
        reply_markup=room_buttons(),
    )

async def show_room(message, room):
    cursor.execute("SELECT id, name, date_out, money FROM people WHERE room=?", (room,))
    rows = cursor.fetchall()

    text = f"🏠 Xona {room}\n\n"
    total = 0
    buttons = []

    for pid, name, date_out, money in rows:
        left = days_left(date_out)
        icon = "🔴" if left <= 3 else ""
        total += money
        text += f"👤 {name} {icon} — ⏳ {left} kun\n"
        buttons.append([InlineKeyboardButton(name, callback_data=f"person_{pid}")])

    text += f"\n📊 Jami: {total} so‘m"

    actions = []
    if len(rows) < ROOM_LIMIT:
        actions.append([InlineKeyboardButton("➕ Odam qo‘shish", callback_data="add")])
    actions.append([InlineKeyboardButton("⬅ Orqaga", callback_data="back")])

    await message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons + actions),
    )

# ================= SCHEDULER =================
async def check_expiring(app):
    cursor.execute("SELECT room, name, date_out FROM people")
    for room, name, date_out in cursor.fetchall():
        if days_left(date_out) == 3:
            await app.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"⚠️ 3 kun qoldi!\n👤 {name}\n🏠 Xona {room}",
            )

# ================= HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Bu bot faqat admin uchun")
        return
    await show_rooms(update.message)

async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "back":
        await show_rooms(query.message)

    elif data.startswith("room_"):
        room = int(data.split("_")[1])
        context.user_data["room"] = room
        await show_room(query.message, room)

    elif data == "add":
        context.user_data["step"] = "name"
        await query.message.reply_text("👤 Ismini yozing:")

    elif data.startswith("person_"):
        pid = int(data.split("_")[1])
        cursor.execute(
            "SELECT name, passport_photo, date_in, date_out, money, room FROM people WHERE id=?",
            (pid,),
        )
        name, photo, din, dout, money, room = cursor.fetchone()
        left = days_left(dout)

        context.user_data["edit_id"] = pid
        context.user_data["room"] = room

        caption = (
            f"👤 {name}\n"
            f"📅 Kelgan: {din}\n"
            f"📅 Ketadi: {dout}\n"
            f"⏳ Qoldi: {left} kun\n"
            f"💵 Pul: {money} so‘m"
        )

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Pulni tahrirlash", callback_data="edit_money")],
            [InlineKeyboardButton("🗑 O‘chirish", callback_data="delete")],
            [InlineKeyboardButton("⬅ Orqaga", callback_data=f"room_{room}")],
        ])

        if photo:
            await query.message.reply_photo(photo=photo, caption=caption, reply_markup=kb)
        else:
            await query.message.reply_text(caption, reply_markup=kb)

    elif data == "delete":
        pid = context.user_data.get("edit_id")
        room = context.user_data.get("room")
        cursor.execute("DELETE FROM people WHERE id=?", (pid,))
        conn.commit()
        context.user_data.clear()
        await show_room(query.message, room)

    elif data == "edit_money":
        context.user_data["step"] = "edit_money"
        await query.message.reply_text("💵 Yangi pul miqdorini yozing:")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")

    if step == "name":
        context.user_data["name"] = update.message.text
        context.user_data["step"] = "passport"
        await update.message.reply_text("🪪 Pasport rasmini yuboring:")

    elif step == "date_out":
        days = int(update.message.text)
        context.user_data["date_out"] = (
            date.today() + timedelta(days=days)
        ).strftime("%Y-%m-%d")
        context.user_data["step"] = "money"
        await update.message.reply_text("💵 Pul miqdori:")

    elif step == "money":
        room = context.user_data["room"]
        cursor.execute(
            "INSERT INTO people (room, name, passport_photo, date_in, date_out, money) VALUES (?,?,?,?,?,?)",
            (
                room,
                context.user_data["name"],
                context.user_data["passport"],
                date.today().strftime("%Y-%m-%d"),
                context.user_data["date_out"],
                int(update.message.text),
            ),
        )
        conn.commit()
        context.user_data.clear()
        await show_room(update.message, room)

    elif step == "edit_money":
        pid = context.user_data["edit_id"]
        room = context.user_data["room"]
        cursor.execute(
            "UPDATE people SET money=? WHERE id=?",
            (int(update.message.text), pid),
        )
        conn.commit()
        context.user_data.clear()
        await show_room(update.message, room)

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("step") == "passport":
        context.user_data["passport"] = update.message.photo[-1].file_id
        context.user_data["step"] = "date_out"
        await update.message.reply_text("📆 Necha kunga qoladi? (masalan 30)")

# ================= MAIN =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_expiring, "interval", days=1, args=[app])
    scheduler.start()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    app.run_polling()
