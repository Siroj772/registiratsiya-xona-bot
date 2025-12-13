
# Telegram 24 Xonali Bot

## Tayyor fayllar
- bot.py
- requirements.txt
- runtime.txt

## Deploy qilish (Render.com)
1. Render.com saytiga kirish va yangi account yaratish.
2. "New → Background Worker" tanlash.
3. GitHub repo bog‘lash (shu fayllar GitHub’da bo‘lishi kerak).
4. Environment:
   - Python 3
   - Build Command: pip install -r requirements.txt
   - Start Command: python bot.py
5. Environment Variables qo‘shish:
   - BOT_TOKEN = [Telegram bot token]
   - ADMIN_ID = [Telegram ID]
6. Deploy bosish va ishga tushirish.

## Bot funksiyalari
- 24 xona, har birida 4 odam
- Tugmalar bilan boshqarish
- Odam qo‘shish, tahrirlash, o‘chirish
- Pul va kun hisoblash
- Pul tugasa ogohlantirish
- Har oyning oxirida xonalar bo‘yicha va umumiy pulni avtomatik admin’ga yuboradi
