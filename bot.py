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
from datetime import datetime

# ================= CONFIG =================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

# ================= DATABASE =================
conn = sqlite3.connect("data.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room INTEGER,
    name TEXT,
    date_in TEXT,
    date_out TEXT,
    money INTEGER
)
""")
conn.commit()

# ================= BUTTONS =================
def room_buttons():
    buttons = []
    for i in range(1, 25, 2):
        buttons.append([
            InlineKeyboardButton(f"Xona {i}", callback_data=f"room_{i}"),
            InlineKeyboardButton(f"Xona {i+1}", callback_data=f"room_{i+1}"),
        ])
    return InlineKeyboardMarkup(buttons)

# ================= HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Bu bot faqat admin uchun")
        return
    await update.message.reply_text("🏠 Xonani tanlang:", reply_markup=room_buttons())

async def room_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("room_"):
        room = int(query.data.split("_")[1])
        context.user_data["room"] = room

        cursor.execute("SELECT id, name, date_in, date_out, money FROM people WHERE room=?", (room,))
        rows = cursor.fetchall()

        text = f"🏠 Xona {room}\n\n"
        if not rows:
            text += "Hozircha odam yo‘q."
        else:
            for r in rows:
                text += f"👤 {r[1]}\n📅 {r[2]} → {r[3]}\n💵 {r[4]} so‘m\n\n"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Odam qo‘shish", callback_data="add")],
            [InlineKeyboardButton("❌ Odam o‘chirish", callback_data="delete")],
            [InlineKeyboardButton("⬅ Orqaga", callback_data="back")],
        ])

        await query.edit_message_text(text, reply_markup=keyboard)

    elif query.data == "back":
        await query.edit_message_text("🏠 Xonani tanlang:", reply_markup=room_buttons())

    elif query.data == "add":
        context.user_data["step"] = "name"
        await query.edit_message_text("👤 Ismini yozing:")

    elif query.data == "delete":
        room = context.user_data.get("room")
        cursor.execute("SELECT id, name FROM people WHERE room=?", (room,))
        rows = cursor.fetchall()
        if not rows:
            await query.edit_message_text("O‘chirish uchun odam yo‘q.")
            return
        buttons = [[InlineKeyboardButton(r[1], callback_data=f"del_{r[0]}")] for r in rows]
        buttons.append([InlineKeyboardButton("⬅ Orqaga", callback_data="back")])
        await query.edit_message_text("Kimni o‘chiramiz?", reply_markup=InlineKeyboardMarkup(buttons))

    elif query.data.startswith("del_"):
        pid = int(query.data.split("_")[1])
        cursor.execute("DELETE FROM people WHERE id=?", (pid,))
        conn.commit()
        await query.edit_message_text("✅ O‘chirildi")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")

    if step == "name":
        context.user_data["name"] = update.message.text
        context.user_data["step"] = "date_out"
        await update.message.reply_text("📅 Ketish sanasi (YYYY-MM-DD):")

    elif step == "date_out":
        context.user_data["date_out"] = update.message.text
        context.user_data["step"] = "money"
        await update.message.reply_text("💵 Pul miqdori:")

    elif step == "money":
        room = context.user_data.get("room")
        name = context.user_data.get("name")
        date_out = context.user_data.get("date_out")
        money = int(update.message.text)
        date_in = datetime.now().strftime("%Y-%m-%d")

        cursor.execute(
            "INSERT INTO people (room, name, date_in, date_out, money) VALUES (?,?,?,?,?)",
            (room, name, date_in, date_out, money),
        )
        conn.commit()

        context.user_data.clear()
        await update.message.reply_text("✅ Odam qo‘shildi. /start bosing")

# ================= MAIN =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(room_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    app.run_polling()

