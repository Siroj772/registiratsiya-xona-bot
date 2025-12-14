from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
import sqlite3, os
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

PRICE_PER_DAY = 26666  # 1 kun = 26 666 so‘m

# ================= DATABASE =================
conn = sqlite3.connect("data.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    room INTEGER,
    telegram_id INTEGER,
    telegram_username TEXT,
    passport_photo TEXT,
    date_out TEXT,
    money INTEGER DEFAULT 0
)
""")
conn.commit()

# ================= HELPERS =================
def calc_new_date(old_date, amount):
    delta = timedelta(seconds=(amount / PRICE_PER_DAY) * 86400)

    if old_date:
        base = datetime.strptime(old_date, "%Y-%m-%d %H:%M")
        if base < datetime.now():
            base = datetime.now()
    else:
        base = datetime.now()

    return base + delta

def remaining(date_out):
    d = datetime.strptime(date_out, "%Y-%m-%d %H:%M")
    diff = d - datetime.now()
    return diff.days, diff.seconds // 3600

# ================= AUTO BIND USER =================
async def auto_bind_user(update: Update):
    user = update.effective_user
    if not user.username:
        return

    cursor.execute("""
        UPDATE people
        SET telegram_id=?
        WHERE telegram_username=?
        AND (telegram_id IS NULL OR telegram_id=0)
    """, (user.id, f"@{user.username}"))
    conn.commit()

# ================= SCHEDULER =================
async def check_expiring(app):
    cursor.execute("SELECT name, room, date_out, telegram_id FROM people")
    for name, room, date_out, tg in cursor.fetchall():
        if not date_out or not tg:
            continue
        days, _ = remaining(date_out)
        if days == 3:
            await app.bot.send_message(
                chat_id=tg,
                text=(
                    "⚠️ Ogohlantirish!\n\n"
                    f"👤 {name}\n"
                    f"🏠 Xona {room}\n"
                    "⏳ Ketish muddatiga 3 kun qoldi"
                )
            )

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await auto_bind_user(update)
    uid = update.effective_user.id

    if uid == ADMIN_ID:
        await update.message.reply_text(
            "👮 Admin panel",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Odam qo‘shish", callback_data="add")],
                [InlineKeyboardButton("💰 Kunlik narx", callback_data="price")]
            ])
        )
    else:
        await update.message.reply_text(
            "👋 Xush kelibsiz!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 To‘lov qilish", callback_data="pay")],
                [InlineKeyboardButton("📄 Mening holatim", callback_data="me")]
            ])
        )

# ================= CALLBACKS =================
async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "add":
        context.user_data.clear()
        context.user_data["step"] = "name"
        await q.message.reply_text("👤 Ismini yozing:")

    elif q.data == "price":
        context.user_data["step"] = "set_price"
        await q.message.reply_text(f"💰 Hozirgi narx: {PRICE_PER_DAY}\nYangi narxni yozing:")

    elif q.data == "pay":
        await q.message.reply_text(
            "💳 To‘lov uchun karta:\n\n8600 **** **** 1234\nSirojiddin S.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ To‘ladim", callback_data="paid")]
            ])
        )

    elif q.data == "paid":
        context.user_data["step"] = "check"
        await q.message.reply_text("📸 To‘lov chekini yuboring")

# ================= TEXT =================
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global PRICE_PER_DAY
    step = context.user_data.get("step")

    if step == "name":
        context.user_data["name"] = update.message.text
        context.user_data["step"] = "telegram"
        await update.message.reply_text(
            "👤 Telegram username (@ali) YOKI Telegram ID yozing:"
        )

    elif step == "telegram":
        tg = update.message.text.strip()
        if tg.startswith("@"):
            context.user_data["telegram_username"] = tg
            context.user_data["telegram_id"] = None
        else:
            context.user_data["telegram_id"] = int(tg)
            context.user_data["telegram_username"] = None

        context.user_data["step"] = "passport"
        await update.message.reply_text("🪪 Pasport rasmini yuboring:")

    elif step == "set_price":
        PRICE_PER_DAY = int(update.message.text)
        context.user_data.clear()
        await update.message.reply_text(f"✅ Kunlik narx {PRICE_PER_DAY} so‘m qilib o‘zgardi")

# ================= PHOTO =================
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("step") == "passport":
        context.user_data["passport_photo"] = update.message.photo[-1].file_id

        cursor.execute("""
            INSERT INTO people
            (name, room, telegram_id, telegram_username, passport_photo)
            VALUES (?,?,?,?,?)
        """, (
            context.user_data["name"],
            1,
            context.user_data.get("telegram_id"),
            context.user_data.get("telegram_username"),
            context.user_data["passport_photo"],
        ))
        conn.commit()

        context.user_data.clear()
        await update.message.reply_text("✅ Odam muvaffaqiyatli qo‘shildi")

    elif context.user_data.get("step") == "check":
        photo = update.message.photo[-1].file_id
        uid = update.effective_user.id

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

# ================= CONFIRM =================
async def confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = int(q.data.split("_")[1])
    context.user_data["confirm"] = uid
    await q.message.reply_text("💰 To‘langan summani yozing:")

async def confirm_sum(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "confirm" not in context.user_data:
        return

    amount = int(update.message.text)
    uid = context.user_data["confirm"]

    cursor.execute("SELECT date_out FROM people WHERE telegram_id=?", (uid,))
    old = cursor.fetchone()[0]

    new_date = calc_new_date(old, amount)

    cursor.execute("""
        UPDATE people
        SET date_out=?, money=money+?
        WHERE telegram_id=?
    """, (
        new_date.strftime("%Y-%m-%d %H:%M"),
        amount,
        uid
    ))
    conn.commit()

    d, h = remaining(new_date.strftime("%Y-%m-%d %H:%M"))
    await update.message.reply_text(
        f"✅ Tasdiqlandi\n➕ {d} kun {h} soat qo‘shildi"
    )
    context.user_data.clear()

# ================= MAIN =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_expiring, "interval", hours=24, args=[app])
    scheduler.start()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(confirm_handler, pattern="^confirm_"))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_sum))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))

    app.run_polling()
