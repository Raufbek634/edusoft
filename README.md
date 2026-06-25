# EduSoft — O'quv markaz boshqaruv tizimi

**Raufbek Turaqulov** tomonidan yaratilgan — o'quvchilar, davomat, to'lovlar, ota-ona portali va Telegram bot.

## Imkoniyatlar

- Admin panel (login sahifasi — bosh sahifa)
- Ota-ona portali (telefon yoki ID orqali)
- Ro'yxatdan o'tish arizasi (`/register`)
- Telegram bot: `/start` → telefon → o'quvchi avtomatik ulanadi
- Shikoyat / taklif / norozilik (sayt va admin xabarlari)
- GitHub + Vercel deploy

## Mahalliy ishga tushirish

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Brauzer: http://localhost:5000  
Default login: `993190712` / `12345678`

## Vercel deploy

1. GitHub ga yuklang (`.env` va haqiqiy `data/settings.json` ni commit qilmang).
2. [Vercel](https://vercel.com) da loyihani import qiling.
3. **Environment Variables** qo'shing:
   - `SECRET_KEY`
   - `BOT_TOKEN`
   - `ADMIN_TELEGRAM_CHAT_ID`
   - `SITE_URL` — masalan `https://your-app.vercel.app`
   - `WEBHOOK_SECRET` (ixtiyoriy)
4. Deploy dan keyin: Admin → Sozlamalar → **Webhook o'rnatish**.
5. Telegram da botingizga `/start` yuborib sinang.

> **Eslatma:** Vercel serverless da JSON fayllar `/tmp` da saqlanadi va qayta deploy da tozalanishi mumkin. Doimiy ma'lumot uchun PostgreSQL (masalan Neon.tech) dan foydalaning.

## Telegram bot

1. [@BotFather](https://t.me/BotFather) dan token oling.
2. [@userinfobot](https://t.me/userinfobot) dan admin `chat_id` oling.
3. Sozlamalarda token va admin chat ID ni kiriting.
4. Ota-ona botda `/start` → telefon yuboradi → tizimdagi bola bilan bog'lanadi.

## Muallif

Raufbek Turaqulov

# edusoft
