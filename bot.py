
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler
import sqlite3
from datetime import datetime
import asyncio
import os

ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
BOT_TOKEN = os.environ.get("BOT_TOKEN")
logging.basicConfig(level=logging.INFO)

conn = sqlite3.connect("data.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room INTEGER,
    name TEXT,
    photo_id TEXT,
    date_in TEXT,
    date_out TEXT,
    money INTEGER
)""")
conn.commit()

def room_buttons():
    buttons = []
    num = 1
    while num <= 24:
        row = [InlineKeyboardButton(f"Xona {num}", callback_data=f"room_{num}"),
               InlineKeyboardButton(f"Xona {num+1}", callback_data=f"room_{num+1}")]
        buttons.append(row)
        num += 2
    return InlineKeyboardMarkup(buttons)

def room_income():
    cursor.execute("SELECT room, SUM(money) FROM people GROUP BY room")
    return cursor.fetchall()

async def send_month_total(app):
    rows = room_income()
    if not rows:
        await app.bot.send_message(chat_id=ADMIN_ID, text="Hozircha pul yo‘q.")
        return
    text = f"💰 {datetime.now().strftime('%B')} oyining oxirigacha ishlangan pul:\n\n"
    total = 0
    for r in rows:
        text += f"Xona {r[0]}: {r[1]} so‘m\n"
        total += r[1]
    text += f"\n📊 Umumiy: {total} so‘m"
    await app.bot.send_message(chat_id=ADMIN_ID, text=text)

def schedule_monthly_report(app):
    scheduler = BackgroundScheduler(timezone="Asia/Tashkent")
    scheduler.add_job(lambda: asyncio.run(send_month_total(app)), 'cron', day='last', hour=23, minute=59)
    scheduler.start()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Bu bot faqat admin uchun!")
        return
    await update.message.reply_text("🏠 Xonani tanlang:", reply_markup=room_buttons())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("room_"):
        room_number = int(data.split("_")[1])
        context.user_data["room"] = room_number
        cursor.execute("SELECT * FROM people WHERE room=?", (room_number,))
        rows = cursor.fetchall()
        text = f"🏠 *Xona {room_number}*\n\n"
        if not rows:
            text += "Hozircha odam yo‘q."
        else:
            for r in rows:
                text += f"👤 {r[2]}\nKelgan: {r[4]}\nKetadigan: {r[5]}\nPul: {r[6]} so‘m\n\n"
        add_button = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Odam qo‘shish", callback_data="add_person")],
            [InlineKeyboardButton("❌ Odam o‘chirish", callback_data="delete_menu")],
            [InlineKeyboardButton("⬅ Orqaga", callback_data="back")]
        ])
        await query.edit_message_text(text, reply_markup=add_button, parse_mode="Markdown")
    elif data == "back":
        await query.edit_message_text("🏠 Xonani tanlang:", reply_markup=room_buttons())

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass  # Avvalgi to'liq kodi shu yerga qo'yiladi

async def month_total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass  # Avvalgi kodi

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.run_polling()
