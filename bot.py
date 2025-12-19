from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from datetime import datetime
import asyncio
import config, db

# ---------- HELP ----------
def days_left(end):
    d = datetime.strptime(end, "%Y-%m-%d")
    return (d - datetime.now()).days

# ---------- START ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if uid in config.ADMINS:
        kb = [[InlineKeyboardButton(f"🏠 Xona {i}", callback_data=f"room_{i}")]
              for i in range(1, config.ROOM_COUNT + 1)]
        await update.message.reply_text(
            "🏨 ADMIN PANEL",
            reply_markup=InlineKeyboardMarkup(kb)
        )
    else:
        p = db.get_person_by_tg(uid)
        if not p:
            await update.message.reply_text("❌ Siz tizimda yo‘qsiz")
            return
        pid, room, name, end, bal = p
        await update.message.reply_text(
            f"👤 {name}\n🏠 Xona {room}\n💰 Balans: {bal}\n⏳ {days_left(end)} kun",
            reply_markup=ReplyKeyboardMarkup([["💳 Pul kiritish"]], resize_keyboard=True)
        )

# ---------- ROOM MENU ----------
async def room_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    room = int(q.data.split("_")[1])
    context.user_data["room"] = room

    kb = [
        [InlineKeyboardButton("➕ Odam qo‘shish", callback_data="add")],
        [InlineKeyboardButton("💳 Karta qo‘shish", callback_data="card")],
        [InlineKeyboardButton("💰 Kunlik narx", callback_data="price")],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="back")]
    ]
    await q.edit_message_text(f"🏠 Xona {room}", reply_markup=InlineKeyboardMarkup(kb))

# ---------- CALLBACK ----------
async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "add":
        if db.people_count(context.user_data["room"]) >= config.MAX_PEOPLE_IN_ROOM:
            await q.message.reply_text("❌ Xona to‘la (4)")
            return
        context.user_data["step"] = "name"
        await q.message.reply_text("👤 Ism:")

    elif data == "card":
        context.user_data["step"] = "card"
        await q.message.reply_text("💳 Karta raqami:")

    elif data == "price":
        context.user_data["step"] = "price"
        await q.message.reply_text("💰 Kunlik narx:")

    elif data.startswith("confirm_"):
        context.user_data["pay"] = int(data.split("_")[1])
        await q.message.reply_text("💰 Qancha pul?")

# ---------- TEXT ----------
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")

    if step == "name":
        context.user_data["name"] = update.message.text
        context.user_data["step"] = "passport"
        await update.message.reply_text("🛂 Passport:")
        return

    if step == "passport":
        context.user_data["passport"] = update.message.text
        context.user_data["step"] = "phone"
        await update.message.reply_text("📞 Telefon:")
        return

    if step == "phone":
        context.user_data["phone"] = update.message.text
        context.user_data["step"] = "end"
        await update.message.reply_text("📅 Ketish sanasi (YYYY-MM-DD):")
        return

    if step == "end":
        db.add_person((
            context.user_data["room"],
            context.user_data["name"],
            context.user_data["passport"],
            context.user_data["phone"],
            update.effective_user.username,
            update.effective_user.id,
            update.message.text,
            0
        ))
        context.user_data.clear()
        await update.message.reply_text("✅ Odam qo‘shildi")
        return

    if step == "card":
        db.set_room_card(context.user_data["room"], update.message.text)
        context.user_data.clear()
        await update.message.reply_text("✅ Karta saqlandi")
        return

    if step == "price":
        db.set_room_price(context.user_data["room"], int(update.message.text))
        context.user_data.clear()
        await update.message.reply_text("✅ Narx saqlandi")
        return

    if update.message.text == "💳 Pul kiritish":
        p = db.get_person_by_tg(update.effective_user.id)
        pid = p[0]
        context.user_data["pid"] = pid
        card = db.get_room_card(p[1])
        await update.message.reply_text(f"💳 Karta:\n{card}\n📸 Chek tashlang")

    if "pay" in context.user_data:
        db.confirm_payment(context.user_data["pay"], int(update.message.text))
        context.user_data.clear()
        await update.message.reply_text("✅ To‘lov tasdiqlandi")

# ---------- PHOTO ----------
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "pid" not in context.user_data:
        return
    pay_id = db.create_payment(context.user_data["pid"])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"confirm_{pay_id}")]
    ])
    for a in config.ADMINS:
        await update.message.forward(a)
        await context.bot.send_message(a, "💰 Yangi chek", reply_markup=kb)
    await update.message.reply_text("⏳ Admin tasdiqlashi kutilmoqda")

# ---------- AUTO ----------
async def auto_check(app):
    while True:
        for pid, name, tg, room, end in db.get_all_people():
            if days_left(end) == config.WARNING_DAYS:
                msg = f"⚠️ {name} | Xona {room} | 2 kun qoldi"
                await app.bot.send_message(tg, msg)
                for a in config.ADMINS:
                    await app.bot.send_message(a, msg)
        await asyncio.sleep(3600)

# ---------- MAIN ----------
async def main():
    app = ApplicationBuilder().token(config.TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(room_menu, pattern="^room_"))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    asyncio.create_task(auto_check(app))
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())


