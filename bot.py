import os, sqlite3
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
PRICE_PER_DAY = 26666
ROOM_LIMIT = 4

conn = sqlite3.connect("data.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS people(
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
conn.commit()

def is_admin(uid):
    cursor.execute("SELECT 1 FROM admins WHERE telegram_id=?", (uid,))
    return cursor.fetchone() is not None

def ensure_admin(uid):
    cursor.execute("SELECT COUNT(*) FROM admins")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO admins VALUES(?)", (uid,))
        conn.commit()

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

def rooms_keyboard():
    kb=[]
    for i in range(1,25,2):
        kb.append([
            InlineKeyboardButton(f"Xona {i}", callback_data=f"room_{i}"),
            InlineKeyboardButton(f"Xona {i+1}", callback_data=f"room_{i+1}")
        ])
    return InlineKeyboardMarkup(kb)

def room_view(room):
    cursor.execute("SELECT id,name,date_out FROM people WHERE room=?", (room,))
    rows=cursor.fetchall()
    text=f"🏠 Xona {room}\n\n"
    kb=[]
    for pid,name,d in rows:
        icon=""
        if d:
            days,_=remaining(d)
            if days<=2: icon="🔴"
        text+=f"👤 {name} {icon}\n"
        kb.append([InlineKeyboardButton(name, callback_data=f"person_{pid}")])
    if len(rows)<ROOM_LIMIT:
        kb.append([InlineKeyboardButton("➕ Odam qo‘shish", callback_data="add_person")])
    kb.append([InlineKeyboardButton("⬅ Orqaga", callback_data="back_rooms")])
    return text, InlineKeyboardMarkup(kb)
async def start(update:Update, context:ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    ensure_admin(uid)
    context.user_data.clear()
    if is_admin(uid):
        await update.message.reply_text("🏠 Xonalar:", reply_markup=rooms_keyboard())
    else:
        await update.message.reply_text(
            "💰 To‘lov",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Pul qo‘shish", callback_data="pay")]
            ])
        )

async def callbacks(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    await q.answer()
    uid=q.from_user.id

    if q.data=="back_rooms":
        context.user_data.clear()
        await q.message.edit_text("🏠 Xonalar:", reply_markup=rooms_keyboard())

    elif q.data.startswith("room_"):
        room=int(q.data.split("_")[1])
        context.user_data["room"]=room
        text,kb=room_view(room)
        await q.message.edit_text(text, reply_markup=kb)

    elif q.data.startswith("person_"):
        pid=int(q.data.split("_")[1])
        context.user_data["pid"]=pid
        cursor.execute("""
        SELECT name,telegram_id,date_out,money FROM people WHERE id=?
        """,(pid,))
        n,tid,d,m=cursor.fetchone()
        text=f"👤 {n}\n💰 {m:,} so‘m\n📅 {d or '-'}"
        await q.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 Pul qo‘shish", callback_data="admin_money")],
                [InlineKeyboardButton("🗑 O‘chirish", callback_data="delete_person")],
                [InlineKeyboardButton("⬅ Orqaga", callback_data=f"room_{context.user_data['room']}")]
            ])
        )

    elif q.data=="delete_person":
        cursor.execute("DELETE FROM people WHERE id=?", (context.user_data["pid"],))
        conn.commit()
        room=context.user_data["room"]
        text,kb=room_view(room)
        await q.message.edit_text(text, reply_markup=kb)

    elif q.data=="add_person":
        context.user_data["step"]="name"
        await q.message.edit_text("👤 Ismni yozing:")

    elif q.data=="admin_money":
        context.user_data["step"]="admin_money"
        await q.message.edit_text("💰 Summani yozing:")
async def text_handler(update:Update, context:ContextTypes.DEFAULT_TYPE):
    step=context.user_data.get("step")
    uid=update.effective_user.id

    if step=="name":
        context.user_data["name"]=update.message.text
        context.user_data["step"]="tid"
        await update.message.reply_text("🆔 Telegram ID:")

    elif step=="tid":
        context.user_data["telegram_id"]=int(update.message.text)
        context.user_data["step"]="passport"
        await update.message.reply_text("🪪 Pasport rasmini yuboring:")

    elif step=="admin_money":
        amount=int(update.message.text)
        pid=context.user_data["pid"]
        cursor.execute("SELECT telegram_id,date_out FROM people WHERE id=?", (pid,))
        tid,old=cursor.fetchone()
        new=calc_new_date(old,amount)
        cursor.execute(
            "UPDATE people SET date_out=?, money=money+? WHERE id=?",
            (new.strftime("%Y-%m-%d %H:%M"),amount,pid)
        )
        cursor.execute(
            "INSERT INTO payments(telegram_id,amount,created_at) VALUES(?,?,?)",
            (tid,amount,datetime.now().strftime("%Y-%m-%d %H:%M"))
        )
        conn.commit()
        await context.bot.send_message(
            tid,
            f"✅ To‘lov qabul qilindi\n💰 {amount:,} so‘m\n📅 {new}"
        )
        room=context.user_data["room"]
        context.user_data.clear()
        text,kb=room_view(room)
        await update.message.reply_text(text, reply_markup=kb)

async def photo_handler(update:Update, context:ContextTypes.DEFAULT_TYPE):
    step=context.user_data.get("step")

    if step=="passport":
        cursor.execute("""
        INSERT INTO people(room,name,telegram_id,passport_photo)
        VALUES(?,?,?,?)
        """,(
            context.user_data["room"],
            context.user_data["name"],
            context.user_data["telegram_id"],
            update.message.photo[-1].file_id
        ))
        conn.commit()
        room=context.user_data["room"]
        context.user_data.clear()
        text,kb=room_view(room)
        await update.message.reply_text(text, reply_markup=kb)

    elif step=="check":
        admin=cursor.execute("SELECT telegram_id FROM admins LIMIT 1").fetchone()[0]
        await context.bot.send_photo(
            admin,
            update.message.photo[-1].file_id,
            caption=f"💳 CHEK\nTelegram ID: {update.effective_user.id}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Tasdiqlash",
                 callback_data=f"confirm_{update.effective_user.id}")]
            ])
        )
        context.user_data.clear()
        await update.message.reply_text("⏳ Chek yuborildi")

async def confirm(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    await q.answer()
    context.user_data["pay_uid"]=int(q.data.split("_")[1])
    context.user_data["step"]="confirm_amount"
    await q.message.edit_text("💰 Summani yozing:")

# MAIN
if __name__=="__main__":
    app=ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(confirm, pattern="^confirm_"))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.run_polling()


