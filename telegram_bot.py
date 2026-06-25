"""Telegram bot — mahalliy polling (localhost) va webhook (Vercel) uchun.
To'lov tizimi: karta -> chek -> admin tasdiqlash -> avtomatik to'lov"""
import os
import re
import time
import threading
import json
import html
import base64
import random
import hashlib
from datetime import datetime, timedelta, timezone

import requests as http_requests

def esc(text):
    """HTML-escape user-controlled text for Telegram parse_mode=HTML."""
    return html.escape(str(text), quote=False)

_poll_lock = threading.Lock()


def get_token(settings):
    return (settings or {}).get('bot_token') or os.environ.get('BOT_TOKEN', '')


def tg_call(token, method, **payload):
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        resp = http_requests.post(url, json=payload, timeout=35)
        return resp.json()
    except Exception as e:
        return {'ok': False, 'description': str(e)}


def send_message(token, chat_id, text, reply_markup=None, parse_mode='HTML'):
    payload = {'chat_id': chat_id, 'text': text}
    if reply_markup:
        payload['reply_markup'] = reply_markup
    if parse_mode:
        payload['parse_mode'] = parse_mode
    data = tg_call(token, 'sendMessage', **payload)
    if data.get('ok'):
        return True
    payload.pop('parse_mode', None)
    data = tg_call(token, 'sendMessage', **payload)
    return data.get('ok', False)


def send_photo(token, chat_id, photo_url, caption='', reply_markup=None):
    payload = {'chat_id': chat_id, 'photo': photo_url, 'caption': caption}
    if reply_markup:
        payload['reply_markup'] = reply_markup
    data = tg_call(token, 'sendPhoto', **payload)
    if data.get('ok'):
        return True
    return send_message(token, chat_id, f"{caption}\n\n🖼 {photo_url}", reply_markup, parse_mode=None)


def phone_keyboard():
    return {
        'keyboard': [[{'text': '📱 Telefon raqamimni yuborish', 'request_contact': True}]],
        'resize_keyboard': True,
        'one_time_keyboard': True
    }


def main_menu_keyboard():
    return {
        'keyboard': [
            [{'text': '👤 Mening ma\'lumotlarim'}, {'text': '💳 To\'lov qilish'}],
            [{'text': '📅 Davomat'}, {'text': '📊 Statistika'}],
            [{'text': '📋 To\'lovlar tarixi'}, {'text': '📞 Admin bilan bog\'lanish'}],
        ],
        'resize_keyboard': True
    }


def channels_keyboard(channels):
    rows = [[{'text': f"📢 {ch}"}] for ch in channels]
    rows.append([{'text': '✅ Obunani tekshirish'}])
    return {'keyboard': rows, 'resize_keyboard': True}


def check_required_channels(token, user_id, channels):
    """Check if user is subscribed to all required channels.
    Returns (ok: bool, missing: list)"""
    if not channels:
        return True, []
    missing = []
    for ch in channels:
        ch_clean = ch.strip().lstrip('@')
        if not ch_clean:
            continue
        try:
            result = tg_call(token, 'getChatMember', chat_id=f"@{ch_clean}", user_id=user_id)
            if result.get('ok'):
                status = result.get('result', {}).get('status', 'left')
                if status in ('left', 'kicked'):
                    missing.append(ch)
            else:
                missing.append(ch)
        except Exception:
            missing.append(ch)
    return len(missing) == 0, missing


def remove_keyboard():
    return {'remove_keyboard': True}


def looks_like_phone(text):
    if not text:
        return False
    digits = re.sub(r'\D', '', text)
    return 9 <= len(digits) <= 15


def handle_update(update, app_context, bot_kg_id=None):
    settings = app_context['load_settings'](bot_kg_id) if bot_kg_id else app_context['load_settings']()
    token = get_token(settings)
    if not token:
        return

    message = update.get('message') or update.get('edited_message')
    if not message:
        cb = update.get('callback_query')
        if cb:
            handle_callback_query(cb, app_context, bot_kg_id)
        return

    chat_id = message['chat']['id']
    text = (message.get('text') or '').strip()
    contact = message.get('contact')
    first_name = message.get('from', {}).get('first_name', 'Ota-ona')
    kg_name = settings.get('name', "Bog'cha")
    site_url = app_context.get('site_url') or os.environ.get('SITE_URL', '')

    # Check for photo (check payment)
    photo = message.get('photo')
    if photo:
        handle_check_photo(chat_id, photo, message, app_context, token, settings, bot_kg_id)
        return

    def ask_phone():
        app_context['save_bot_session'](chat_id, 'await_phone')
        send_message(
            token, chat_id,
            f"👋 Salom, <b>{esc(first_name)}</b>!\n\n"
            f"🏫 <b>{esc(kg_name)}</b> botiga xush kelibsiz.\n\n"
            f"Farzandingizni bog'lash uchun <b>telefon raqamingizni</b> yuboring.\n"
            f"📱 Tugmani bosing yoki raqam yozing: <code>998901234567</code>",
            reply_markup=phone_keyboard()
        )

    if text.startswith('/start') or text.startswith('/help') or text.lower() in ('start', 'boshlash', 'salom'):
        ask_phone()
        return

    session = app_context['get_bot_session'](chat_id)
    step = session.get('step', 'start')

    session_phone = session.get('phone', '')
    student, found_kg_id = find_student(session_phone, app_context, bot_kg_id)

    # ── Payment steps: handle text (not photo) ──────────────────────
    if step == 'pay_await_card':
        send_message(token, chat_id,
            "📸 Iltimos, to'lov chek rasmini (skrinshot/foto) yuboring.\n"
            "Agar bekor qilmoqchi bo'lsangiz /start bosing.",
            reply_markup=remove_keyboard())
        return

    if step == 'pay_await_amount':
        handle_pay_amount(chat_id, text, student, found_kg_id, app_context, token, settings)
        return

    # ── Await channels step (must join required channels) ────────────
    if step == 'await_channels':
        session_channels = session.get('channels', [])
        if text == '✅ Obunani tekshirish':
            ok, missing = check_required_channels(token, chat_id, session_channels)
            if ok:
                app_context['save_bot_session'](chat_id, 'linked', {'phone': session_phone or session.get('phone', '')})
                portal = f"{site_url.rstrip('/')}/parent?phone={session.get('phone', '')}" if site_url else ''
                send_message(
                    token, chat_id,
                    f"✅ <b>Rahmat!</b> Barcha kanallarga obuna bo'ldingiz.\n\n"
                    f"Quyidagi tugmalar orqali boshqaring:",
                    reply_markup=main_menu_keyboard()
                )
                return
            else:
                msg = "❌ Quyidagi kanallarga hali obuna bo'lmagansiz:\n\n"
                for ch in session_channels:
                    ch_clean = ch.strip().lstrip('@')
                    icon = '✅' if ch not in missing else '❌'
                    msg += f"{icon} <a href='https://t.me/{esc(ch_clean)}'>@{esc(ch_clean)}</a>\n"
                msg += "\n📢 Kanallarga obuna bo'ling va qayta tekshiring."
                send_message(token, chat_id, msg, reply_markup=channels_keyboard(session_channels))
                return
        # User clicked a channel link (or other text)
        send_message(token, chat_id,
            "📢 Avval quyidagi kanallarga obuna bo'ling, so'ng ✅ tugmasini bosing.",
            reply_markup=channels_keyboard(session_channels))
        return

    # ── Handle linked menu ─────────────────────────────────────────
    if step == 'linked':
        if text == '💳 To\'lov qilish':
            kg_id = found_kg_id or bot_kg_id
            start_payment_flow(chat_id, student, kg_id, app_context, token, settings)
            return
        if text == '👤 Mening ma\'lumotlarim' and student:
            show_student_info(chat_id, student, token, settings, site_url)
            return
        if text == '📅 Davomat' and student:
            kg_id = found_kg_id or bot_kg_id
            show_attendance(chat_id, student, kg_id, app_context, token)
            return
        if text == '📞 Admin bilan bog\'lanish':
            admin_phone = settings.get('admin_phone', '')
            msg = f"Admin bilan bog'lanish uchun:\n📞 {esc(admin_phone) or 'Telefon raqam mavjud emas'}"
            send_message(token, chat_id, msg)
            return
        if text == '📊 Statistika' and student:
            kg_id = found_kg_id or bot_kg_id
            show_statistics(chat_id, student, kg_id, app_context, token)
            return
        if text == '📋 To\'lovlar tarixi' and student:
            kg_id = found_kg_id or bot_kg_id
            show_payment_history(chat_id, student, kg_id, app_context, token)
            return
        send_message(token, chat_id,
            "Quyidagi tugmalardan foydalaning:",
            reply_markup=main_menu_keyboard())
        return

    # ── Phone linking flow ──────────────────────────────────────────
    phone_raw = ''
    if contact:
        phone_raw = contact.get('phone_number', '')
    elif looks_like_phone(text):
        phone_raw = text

    if not phone_raw and step == 'await_phone' and text and not text.startswith('/'):
        phone_raw = text

    if phone_raw:
        norm = app_context['normalize_phone'](phone_raw)
        if len(norm) >= 9:
            student, status, link_kg_id = app_context['link_telegram'](chat_id, norm, bot_kg_id)
            if status == 'linked' and student:
                app_context['save_bot_session'](chat_id, 'linked', {'phone': norm})
                linked_kg_id = link_kg_id or found_kg_id or bot_kg_id
                # Check required channels
                channels = settings.get('required_channels', [])
                if channels:
                    ok, missing = check_required_channels(token, chat_id, channels)
                    if not ok:
                        app_context['save_bot_session'](chat_id, 'await_channels', {'phone': norm, 'channels': channels})
                        msg = "📢 <b>Majburiy kanallar</b>\n\nQuyidagi kanallarga obuna bo'ling va ✅ tugmasini bosing:\n\n"
                        for ch in channels:
                            ch_clean = ch.strip().lstrip('@')
                            msg += f"📢 <a href='https://t.me/{ch_clean}'>@{ch_clean}</a>\n"
                        msg += "\n<b>Botdan foydalanish uchun barcha kanallarga obuna bo'lishingiz kerak!</b>"
                        send_message(token, chat_id, msg, reply_markup=channels_keyboard(channels))
                        return
                portal = f"{site_url.rstrip('/')}/parent?phone={norm}" if site_url else f"/parent?phone={norm}"
                send_message(
                    token, chat_id,
                    f"✅ <b>Muvaffaqiyatli!</b>\n\n"
                    f"👨‍🎓 <b>{esc(student['first_name'])} {esc(student['last_name'])}</b>\n"
                    f"📚 Guruh: {esc(student.get('group', '—'))}\n\n"
                    f"Quyidagi tugmalar orqali boshqaring:",
                    reply_markup=main_menu_keyboard()
                )
                app_context['notify_admin'](
                    f"📱 Telegram ulandi: {esc(student['first_name'])} {esc(student['last_name'])} "
                    f"({esc(student.get('parent_name', ''))}, {esc(norm)})",
                    'info',
                    kg_id=linked_kg_id
                )
                return
            else:
                reg = f"{site_url.rstrip('/')}/register" if site_url else '/register'
                send_message(
                    token, chat_id,
                    f"⚠️ Bu raqam tizimda yo'q.\n\n"
                    f"Avval ro'yxatdan o'ting:\n🌐 {reg}\n\n"
                    f"Keyin yana /start yuboring.",
                    reply_markup=remove_keyboard()
                )
                app_context['notify_admin'](
                    f"📱 Noma'lum telefon: {norm} (chat_id: {chat_id})",
                    'warning'
                )
                return
        else:
            send_message(token, chat_id, "❌ Noto'g'ri raqam. Masalan: <code>998901234567</code>")
            return

    # ── No phone yet, ask ───────────────────────────────────────────
    ask_phone()


def find_student(phone, app_context, kg_id=None):
    norm = app_context['normalize_phone'](phone)
    if not norm:
        return None, None
    students_data = find_student_by_phone_all(norm, app_context, kg_id)
    if students_data:
        return students_data[0], students_data[1]
    return None, None


def find_student_by_phone_all(norm, app_context, kg_id=None):
    """Find all students with this phone — optionally restricted to one kindergarten."""
    try:
        from app import pc, normalize_phone
        kindergartens = [kg for kg in pc.load_kindergartens() if kg.get('status') == 'active']
        if kg_id:
            kindergartens = [kg for kg in kindergartens if kg['id'] == kg_id]
        for kg in kindergartens:
            students = pc.load_json('students.json', kg['id'])
            for s in students:
                sp = normalize_phone(s.get('parent_phone', ''))
                if sp and (sp == norm or norm.endswith(sp[-9:]) or sp.endswith(norm[-9:])):
                    return s, kg['id']
    except Exception as e:
        print(f"[ERROR] find_student_by_phone_all: {e}")
        return None


def payment_provider_info(settings):
    """Get payment provider display info based on settings."""
    provider = settings.get('payment_provider', 'manual_card')
    card = settings.get('payment_card', '')
    merchant = settings.get('payment_merchant_id', '')
    service = settings.get('payment_service_id', '')

    if provider == 'tezcheck':
        info = "🔵 <b>TezCheck</b>\n"
        return info
    elif provider == 'click':
        info = "🔘 <b>CLICK</b>\n"
        if merchant:
            info += f"🆔 Merchant ID: <code>{esc(merchant)}</code>\n"
        if service:
            info += f"🔢 Service ID: <code>{esc(service)}</code>\n"
        if card:
            info += f"💳 Karta: <code>{esc(card)}</code>\n"
        return info
    elif provider == 'uzum':
        info = "🟢 <b>Uzum</b>\n"
        if merchant:
            info += f"🆔 Merchant ID: <code>{esc(merchant)}</code>\n"
        if card:
            info += f"💳 Karta: <code>{esc(card)}</code>\n"
        return info
    elif provider == 'payme':
        info = "🔵 <b>Payme</b>\n"
        if merchant:
            info += f"🆔 Merchant ID: <code>{esc(merchant)}</code>\n"
        if card:
            info += f"💳 Karta: <code>{esc(card)}</code>\n"
        return info
    else:
        info = "💳 <b>Bank kartasi</b>\n"
        if card:
            info += f"🏦 Karta: <code>{esc(card)}</code>\n"
        return info


def start_payment_flow(chat_id, student, kg_id, app_context, token, settings):
    """Start the payment process: ask for amount"""
    if not student:
        send_message(token, chat_id, "❌ Farzandingiz topilmadi. /start bosing va qayta ulaning.")
        return

    app_context['save_bot_session'](chat_id, 'pay_await_amount', {'phone': app_context['get_bot_session'](chat_id).get('phone', '')})

    pinfo = payment_provider_info(settings)
    msg = (
        f"💳 <b>To'lov tizimi</b>\n\n"
        f"👨‍🎓 Farzand: <b>{esc(student['first_name'])} {esc(student['last_name'])}</b>\n"
        f"💵 Oylik to'lov: <b>{int(student.get('monthly_fee', 0)):,} UZS</b>\n\n"
        f"{pinfo}\n"
    )
    msg += "📝 <b>To'lov miqdorini kiriting (UZS):</b>"
    send_message(token, chat_id, msg)


def handle_pay_amount(chat_id, text, student, kg_id, app_context, token, settings):
    """Handle amount input, ask for card number or create tezcheck invoice."""
    try:
        amount = int(text.replace(' ', '').replace(',', ''))
        if amount <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        send_message(token, chat_id, "❌ Noto'g'ri miqdor. Iltimos, faqat son kiriting (masalan: 500000)")
        return

    provider = settings.get('payment_provider', 'manual_card')
    if provider == 'tezcheck':
        pc = (app_context or {}).get('pc')
        parent_name = student.get('parent_name', '')
        parent_phone = student.get('parent_phone', '') or app_context.get('get_bot_session', lambda x: {})(chat_id).get('phone', '')
        site_url = (app_context or {}).get('site_url', 'https://sofgardercrm.vercel.app').rstrip('/')
        import urllib.parse
        params = urllib.parse.urlencode({'name': parent_name, 'phone': parent_phone})
        pay_url = f"{site_url}/tezcheck-pay/{kg_id}?{params}"
        msg = (
            f"💳 <b>To'lov tizimi</b>\n\n"
            f"👨‍🎓 Farzand: <b>{esc(student['first_name'])} {esc(student['last_name'])}</b>\n"
            f"💵 Miqdor: <b>{amount:,} UZS</b>\n\n"
            f"🔵 <b>TezCheck</b>\n\n"
            f"To'lov qilish uchun quyidagi havolani bosing:\n"
            f"🔗 <a href='{pay_url}'>To'lov sahifasi</a>"
        )
        kb = {'inline_keyboard': [[{'text': '💳 To\'lov qilish', 'url': pay_url}]]}
        send_message(token, chat_id, msg, reply_markup=kb)
        return

    app_context['save_bot_session'](chat_id, 'pay_await_card', {
        'phone': app_context['get_bot_session'](chat_id).get('phone', ''),
        'pay_amount': amount
    })

    pinfo = payment_provider_info(settings)
    msg = (
        f"💳 <b>To'lov ma'lumotlari</b>\n\n"
        f"Miqdor: <b>{amount:,} UZS</b>\n"
        f"{pinfo}\n"
    )
    msg += "✅ <b>Pulni o'tkazing</b> va <b>chek rasmini</b> yuboring (foto yoki skrinshot).\n\n"
    msg += "📸 <i>Chek rasmni hozir yuboring...</i>"
    send_message(token, chat_id, msg)


def handle_check_photo(chat_id, photo, message, app_context, token, settings, bot_kg_id=None):
    """Handle check photo upload from parent"""
    session = app_context['get_bot_session'](chat_id)
    step = session.get('step', '')
    if step != 'pay_await_card':
        if step != 'linked':
            send_message(token, chat_id, "❌ Rasm qabul qilinmadi. Avval /start bosing yoki 💳 To'lov qilishni bosing.")
            return
        send_message(token, chat_id, "❌ Rasm qabul qilinmadi. Iltimos, avval 💳 To'lov qilish tugmasini bosing.")
        return

    pay_amount = session.get('pay_amount', 0)
    if not pay_amount:
        send_message(token, chat_id, "❌ Xatolik yuz berdi. Qaytadan 💳 To'lov qilish tugmasini bosing.")
        return

    phone = session.get('phone', '')
    file_id = photo[-1]['file_id']

    try:
        file_info = tg_call(token, 'getFile', file_id=file_id)
        if not file_info.get('ok'):
            send_message(token, chat_id, "❌ Rasm yuklab bo'lmadi. Qayta urinib ko'ring.")
            return
        file_path = file_info['result']['file_path']
        file_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        # Download and convert to base64 for permanent storage
        file_resp = http_requests.get(file_url, timeout=30)
        if file_resp.status_code == 200:
            b64 = base64.b64encode(file_resp.content).decode('utf-8')
            ctype = file_resp.headers.get('content-type', 'image/jpeg')
            photo_url = f"data:{ctype};base64,{b64}"
        else:
            # Fallback to direct URL (may expire)
            photo_url = file_url
    except Exception:
        send_message(token, chat_id, "❌ Rasm yuklab bo'lmadi.")
        return

    # Find student info
    student, kg_id = find_student(phone, app_context, bot_kg_id)
    if not student:
        student = {'id': 'UNKNOWN', 'first_name': 'Noma\'lum', 'last_name': '', 'parent_name': '', 'parent_phone': phone}

    # Save check to database
    try:
        from app import load_json, save_json, datetime, uuid
        checks = load_json('payment_checks.json', kg_id)
        check_id = 'CHK-' + str(uuid.uuid4())[:8].upper()
        receipt_id = 'RCP-' + str(uuid.uuid4())[:8].upper()

        # Create pending payment record immediately
        payments = load_json('payments.json', kg_id)
        pending_payment = {
            'id': receipt_id,
            'student_id': student['id'],
            'student_name': f"{student['first_name']} {student['last_name']}",
            'amount': pay_amount,
            'date': datetime.now().strftime('%Y-%m-%d'),
            'month': datetime.now().strftime('%Y-%m'),
            'type': 'partial',
            'category': 'tuition',
            'status': 'pending',
            'note': f"Chek orqali to'lov",
            'admin_name': 'Kutilmoqda',
            'created_at': datetime.now().isoformat()
        }
        payments.append(pending_payment)
        save_json('payments.json', payments, kg_id)

        check_data = {
            'id': check_id,
            'receipt_id': receipt_id,
            'student_id': student['id'],
            'student_name': f"{student['first_name']} {student['last_name']}",
            'parent_phone': phone,
            'parent_chat_id': str(chat_id),
            'amount': pay_amount,
            'photo_url': photo_url,
            'status': 'pending',
            'created_at': datetime.now().isoformat()
        }
        checks.append(check_data)
        save_json('payment_checks.json', checks, kg_id)
    except Exception as e:
        send_message(token, chat_id, f"❌ Saqlashda xatolik: {str(e)}")
        return

    # Reset session
    app_context['save_bot_session'](chat_id, 'linked', {'phone': phone})

    # Send receipt to parent
    send_message(token, chat_id,
        f"✅ <b>Chek qabul qilindi!</b>\n\n"
        f"💳 To'lov summasi: <b>{pay_amount:,} UZS</b>\n"
        f"🆔 Chek ID: <code>{check_id}</code>\n\n"
        f"⏳ Admin tomonidan tasdiqlanishi kutilmoqda. Tez orada xabar beramiz.",
        reply_markup=main_menu_keyboard())

    # Notify admin
    admin_chat = settings.get('admin_telegram_chat_id', '')
    if admin_chat:
        admin_msg = (
            f"📩 <b>Yangi to'lov cheki</b>\n\n"
            f"👤 Ota-ona: <b>{esc(student.get('parent_name', 'Noma\'lum'))}</b>\n"
            f"📞 Telefon: {esc(phone)}\n"
            f"👨‍🎓 Farzand: <b>{esc(student['first_name'])} {esc(student['last_name'])}</b>\n"
            f"💵 Summa: <b>{pay_amount:,} UZS</b>\n"
            f"🆔 ID: <code>{check_id}</code>\n\n"
            f"Chek rasmini tekshirib, tasdiqlang!"
        )
        approve_btn = {
            'inline_keyboard': [[
                {'text': '✅ Tasdiqlash', 'callback_data': f'approve_pay_{kg_id}_{check_id}'},
                {'text': '❌ Rad etish', 'callback_data': f'reject_pay_{kg_id}_{check_id}'}
            ]]
        }
        send_photo(token, admin_chat, photo_url, admin_msg, reply_markup=approve_btn)

    app_context['notify_admin'](
        f"📩 Yangi to'lov cheki: {esc(student['first_name'])} {esc(student['last_name'])} — {pay_amount:,} UZS — "
        f"Chek ID: {check_id}",
        'payment',
        kg_id=kg_id
    )


def handle_pay_card(chat_id, text, student, kg_id, app_context, token, settings):
    """Handle when user enters a card number manually (fallback)"""
    # Just re-prompt for check photo
    send_message(token, chat_id,
        "📸 Iltimos, to'lov chek rasmini (skrinshot/foto) yuboring.")


def show_statistics(chat_id, student, kg_id, app_context, token):
    try:
        from app import load_json
        now = datetime.now(timezone.utc)
        month = now.strftime('%Y-%m')
        # Attendance this month
        att = load_json('attendance.json', kg_id)
        month_att = [a for a in att if a['student_id'] == student['id'] and a.get('date', '').startswith(month)]
        total_days = len(month_att)
        present_days = sum(1 for a in month_att if a['status'] == 'present')
        att_pct = round(present_days / total_days * 100) if total_days else 0
        # Payments this month
        pays = load_json('payments.json', kg_id)
        student_pays = [p for p in pays if p['student_id'] == student['id'] and p.get('status') != 'cancelled']
        month_pays = [p for p in student_pays if p.get('date', '').startswith(month)]
        month_total = sum(p.get('amount', 0) for p in month_pays)
        all_total = sum(p.get('amount', 0) for p in student_pays)
        # Monthly fee
        fee = int(student.get('monthly_fee', 0))
        # Attendance bar
        bar_len = 10
        filled = round(att_pct / 100 * bar_len)
        bar = '🟩' * filled + '⬜' * (bar_len - filled)
        lines = [
            f"📊 <b>Statistika</b>",
            f"👨‍🎓 {esc(student['first_name'])} {esc(student['last_name'])}",
            f"📚 {esc(student.get('group', '—'))}",
            f"",
            f"<b>📅 Davomat ({month}):</b>",
            f"{bar} <b>{att_pct}%</b>",
            f"✅ Kelgan: {present_days}/{total_days} kun",
            f"",
            f"<b>💳 To'lovlar:</b>",
            f"📆 Shu oy: <b>{month_total:,} UZS</b>",
        ]
        if all_total:
            lines.append(f"💰 Jami: <b>{all_total:,} UZS</b>")
        if fee:
            lines.append(f"📋 Oylik: <b>{fee:,} UZS</b>")
            if fee > month_total:
                debt = fee - month_total
                lines.append(f"⚠️ Qarz: <b>{debt:,} UZS</b>")
        site_url = app_context.get('site_url') or os.environ.get('SITE_URL', '')
        kb = None
        if site_url:
            portal_url = f"{site_url.rstrip('/')}/parent?phone={student.get('parent_phone', '')}"
            kb = {'inline_keyboard': [
                [{'text': '🌐 Ota-ona portali', 'url': portal_url}],
                [{'text': '💳 To\'lov qilish', 'callback_data': 'stat_pay_' + kg_id}]
            ]}
        send_message(token, chat_id, '\n'.join(filter(None, lines)), reply_markup=kb)
    except Exception as e:
        print(f"[ERROR] show_statistics: {e}")
        send_message(token, chat_id, "📊 Statistika yuklanmadi.")

def show_student_info(chat_id, student, token, settings, site_url):
    portal = f"{site_url.rstrip('/')}/parent?phone={student.get('parent_phone', '')}" if site_url else ''
    msg = (
        f"👤 <b>Farzandingiz haqida</b>\n\n"
        f"👨‍🎓 Ism: <b>{esc(student['first_name'])} {esc(student['last_name'])}</b>\n"
        f"📚 Guruh: {esc(student.get('group', '—'))}\n"
        f"💳 Oylik to'lov: <b>{int(student.get('monthly_fee', 0)):,} UZS</b>\n"
        f"📅 Qo'shilgan: {esc(student.get('join_date', '—'))}\n"
        f"📞 Ota-ona: {esc(student.get('parent_name', '—'))} ({esc(student.get('parent_phone', '—'))})\n"
    )
    if portal:
        msg += f"\n🌐 <a href='{portal}'>Ota-ona portali</a>"
    send_message(token, chat_id, msg)


def show_attendance(chat_id, student, kg_id, app_context, token):
    try:
        from app import load_json
        att = load_json('attendance.json', kg_id)
        student_att = [a for a in att if a['student_id'] == student['id']]
        student_att = sorted(student_att, key=lambda x: x.get('date', ''), reverse=True)[:10]
        if not student_att:
            send_message(token, chat_id, "📅 Davomat ma'lumoti yo'q.")
            return
        msg = "📅 <b>So'nggi davomat:</b>\n\n"
        for a in student_att:
            status_map = {'present': '✅ Keldi', 'absent': '❌ Kelmadi', 'excused': '⚠️ Sababli'}
            status = status_map.get(a['status'], a['status'])
            msg += f"• {esc(a['date'])}: {esc(status)}\n"
        send_message(token, chat_id, msg)
    except Exception:
        send_message(token, chat_id, "📅 Davomat ma'lumoti yo'q.")


def show_payment_history(chat_id, student, kg_id, app_context, token):
    try:
        from app import load_json
        payments = load_json('payments.json', kg_id)
        print(f"[DEBUG] show_payment_history: kg_id={kg_id}, total_payments={len(payments)}, student_id={student['id']}")
        student_pay = [p for p in payments if p['student_id'] == student['id'] and p.get('status', 'paid') != 'cancelled']
        student_pay = sorted(student_pay, key=lambda x: x.get('date', ''), reverse=True)[:10]
        if not student_pay:
            send_message(token, chat_id, "💳 To'lov tarixi yo'q.")
            return
        site_url = app_context.get('site_url') or os.environ.get('SITE_URL', '')
        msg = "💳 <b>To'lov tarixi:</b>\n\n"
        for p in student_pay:
            st = p.get('status', 'paid')
            st_icon = {'paid': '✅', 'pending': '⏳', 'cancelled': '❌', 'refunded': '↩️'}.get(st, '✅')
            receipt_url = f"{site_url}/receipt/{p['id']}" if site_url else ''
            link = f'<a href="{receipt_url}">📄 Chek</a>' if receipt_url else ''
            msg += f"{st_icon} {esc(p['date'])}: <b>{int(p['amount']):,} UZS</b> — {esc(p.get('type', 'full'))} {link}\n"
        msg += "\n✅ To'lovlar tarixi."
        # Add share button for the most recent payment
        latest = student_pay[0]
        kb = None
        if site_url:
            latest_url = f"{site_url}/receipt/{latest['id']}"
            kb = {'inline_keyboard': [[{'text': '📤 Chekni ulashish', 'url': latest_url}]]}
        send_message(token, chat_id, msg, reply_markup=kb)
    except Exception:
        send_message(token, chat_id, "💳 To'lov tarixi yo'q.")


def run_polling(app_context, kg_id=None):
    settings = app_context['load_settings'](kg_id) if kg_id else app_context['load_settings']()
    token = get_token(settings)
    if not token:
        name = settings.get('name', 'Noma\'lum')
        print(f"[Telegram] {name}: Token yo'q")
        return

    # Create a per-bot offset so each bot tracks its own updates
    local_offset = 0

    tg_call(token, 'deleteWebhook', drop_pending_updates=False)
    name = settings.get('name', 'Noma\'lum')
    print(f"[Telegram] {name}: Bot polling ishlayapti (token: ...{token[-6:]})")

    def handle_update_for_kg(upd):
        """Wrap handle_update with the correct kg_id context."""
        cb = upd.get('callback_query')
        if cb:
            handle_callback_query(cb, app_context, bot_kg_id=kg_id)
            return
        message = upd.get('message') or upd.get('edited_message')
        if not message:
            return
        chat_id = message['chat']['id']
        if kg_id:
            kg_settings = app_context['load_settings'](kg_id)
        else:
            kg_settings = settings
        msg_token = get_token(kg_settings)
        if msg_token != token:
            return
        handle_update(upd, app_context, bot_kg_id=kg_id)

    while True:
        try:
            data = tg_call(token, 'getUpdates', offset=local_offset, timeout=25)
            if not data.get('ok'):
                time.sleep(3)
                continue
            for upd in data.get('result', []):
                local_offset = upd['update_id'] + 1
                try:
                    handle_update_for_kg(upd)
                except Exception as ex:
                    print(f"[Telegram] xabar xato ({name}): {ex}")
        except Exception as ex:
            print(f"[Telegram] ulanish xato ({name}): {ex}")
            time.sleep(4)


def handle_callback_query(cb, app_context, bot_kg_id=None):
    """Handle inline keyboard callbacks (admin approve/reject payments)"""
    data = cb.get('data', '')
    chat_id = cb['message']['chat']['id']
    msg_id = cb['message']['message_id']
    cb_id = cb['id']

    # Extract kg_id from callback data; fallback to bot_kg_id
    cb_kg_id = bot_kg_id
    if data.startswith('approve_pay_') or data.startswith('reject_pay_'):
        parts = data.split('_', 3)
        if len(parts) >= 4:
            cb_kg_id = parts[2]
    settings = app_context['load_settings'](cb_kg_id)
    token = get_token(settings)
    if not token:
        print(f"[WARN] callback token topilmadi: cb_kg_id={cb_kg_id}")
        try:
            tg_call(token or cb_kg_id, 'answerCallbackQuery', callback_query_id=cb_id,
                text="Bot sozlanmagan. Admin bilan bog'laning.")
        except Exception:
            pass
        return

    if data.startswith('approve_pay_') or data.startswith('reject_pay_'):
        approved = data.startswith('approve_pay_')
        parts = data.split('_', 3)
        if len(parts) >= 4:
            kg_id, check_id = parts[2], parts[3]
        else:
            print(f"[WARN] Malformed callback data (cannot parse): {data}")
            tg_call(token, 'answerCallbackQuery', callback_query_id=cb_id,
                text="Xato: noto'g'ri ma'lumot.")
            return
        approve_check(chat_id, msg_id, cb_id, kg_id, check_id, token, app_context, approved=approved)
    elif data.startswith('stat_pay_'):
        kg_id = data.split('_', 2)[2] if len(data.split('_', 2)) >= 3 else bot_kg_id
        tg_call(token, 'answerCallbackQuery', callback_query_id=cb_id,
            text="💳 To'lovga o'tkazilmoqda...")
        session = app_context['get_bot_session'](chat_id)
        phone = session.get('phone', '')
        student, found_kg_id = find_student(phone, app_context, kg_id)
        if student and found_kg_id:
            start_payment_flow(chat_id, student, found_kg_id, app_context, token, settings)
    else:
        tg_call(token, 'answerCallbackQuery', callback_query_id=cb_id)


def approve_check(chat_id, msg_id, cb_id, kg_id, check_id, token, app_context, approved=True):
    """Admin approves or rejects a payment check"""
    try:
        from app import load_json, save_json, datetime
        from app import pc

        now = datetime.now()
        checks = load_json('payment_checks.json', kg_id)
        check = next((c for c in checks if c['id'] == check_id), None)

        if not check:
            tg_call(token, 'editMessageText',
                chat_id=chat_id, message_id=msg_id,
                text="❌ Chek topilmadi yoki allaqachon tasdiqlangan.")
            tg_call(token, 'answerCallbackQuery', callback_query_id=cb_id)
            return

        if check.get('status') != 'pending':
            tg_call(token, 'editMessageText',
                chat_id=chat_id, message_id=msg_id,
                text=f"⚠️ Bu chek allaqachon {check['status']}.")
            tg_call(token, 'answerCallbackQuery', callback_query_id=cb_id)
            return

        receipt_id = check.get('receipt_id', 'RCP-' + check_id[4:])
        base_url = app_context.get('site_url', '').rstrip('/')

        # Update existing pending payment in payments.json
        payments = load_json('payments.json', kg_id)
        payment_updated = False
        for p in payments:
            if p['id'] == receipt_id:
                if approved:
                    p['status'] = 'paid'
                    p['date'] = now.strftime('%Y-%m-%d')
                    p['admin_name'] = 'Admin (Telegram)'
                else:
                    p['status'] = 'cancelled'
                    p['admin_name'] = 'Admin (Telegram)'
                payment_updated = True
                break

        if not payment_updated:
            # Fallback: create new payment (for legacy checks without receipt_id)
            new_payment = {
                'id': receipt_id,
                'student_id': check['student_id'],
                'student_name': check['student_name'],
                'amount': check['amount'],
                'date': now.strftime('%Y-%m-%d'),
                'month': now.strftime('%Y-%m'),
                'type': 'check',
                'category': 'tuition',
                'status': 'paid' if approved else 'cancelled',
                'note': f"Chek orqali to'lov (ID: {check_id})",
                'admin_name': 'Admin (Telegram)',
                'created_at': now.isoformat()
            }
            payments.append(new_payment)
        save_json('payments.json', payments, kg_id)

        # Update check status
        for i, c in enumerate(checks):
            if c['id'] == check_id:
                if approved:
                    checks[i]['status'] = 'approved'
                    checks[i]['payment_id'] = receipt_id
                    checks[i]['approved_at'] = now.isoformat()
                else:
                    checks[i]['status'] = 'rejected'
                break
        save_json('payment_checks.json', checks, kg_id)

        # Notify parent
        parent_chat = check.get('parent_chat_id', '')
        if parent_chat:
            if approved:
                if base_url:
                    qr_full_url = f"{base_url}/api/receipt/{receipt_id}/qr"
                    caption = (
                        f"✅ <b>To'lov tasdiqlandi!</b>\n\n"
                        f"💵 Summa: <b>{check['amount']:,} UZS</b>\n"
                        f"🧾 Chek ID: <code>{receipt_id}</code>\n"
                        f"📅 Sana: {now.strftime('%d.%m.%Y')}\n\n"
                        f"Rahmat! To'lovingiz qabul qilindi. 🙏"
                    )
                    send_photo(token, parent_chat, qr_full_url, caption=caption,
                        reply_markup=main_menu_keyboard())
                else:
                    send_message(token, parent_chat,
                        f"✅ <b>To'lov tasdiqlandi!</b>\n\n"
                        f"💵 Summa: <b>{check['amount']:,} UZS</b>\n"
                        f"🧾 Chek ID: <code>{receipt_id}</code>\n"
                        f"📅 Sana: {now.strftime('%d.%m.%Y')}\n\n"
                        f"Rahmat! To'lovingiz qabul qilindi. 🙏",
                        reply_markup=main_menu_keyboard())
            else:
                send_message(token, parent_chat,
                    f"❌ <b>To'lov rad etildi</b>\n\n"
                    f"💵 Summa: <b>{check['amount']:,} UZS</b>\n"
                    f"ℹ️ Sabab: Admin tomonidan rad etildi.\n"
                    f"Iltimos, admin bilan bog'laning yoki qayta to'lov qiling.",
                    reply_markup=main_menu_keyboard())

        # Update admin message
        label = "✅ TASDIQLANDI" if approved else "❌ RAD ETILDI"
        tg_call(token, 'editMessageCaption',
            chat_id=chat_id, message_id=msg_id,
            caption=f"<b>{label}</b>\n\n{check['student_name']} — {check['amount']:,} UZS\n{check_id}\n\nChek ID: {receipt_id}")

        tg_call(token, 'answerCallbackQuery', callback_query_id=cb_id)

    except Exception as e:
        tg_call(token, 'answerCallbackQuery', callback_query_id=cb_id, text=f"Xatolik: {str(e)[:50]}")


def start_polling_background(app_context):
    if os.environ.get('VERCEL'):
        return False
    if os.environ.get('TELEGRAM_POLLING', '1').strip() == '0':
        return False

    # Get all kindergarten IDs with bot tokens
    try:
        from app import pc
        kgs = pc.load_kindergartens()
    except Exception:
        kgs = []

    if not kgs:
        settings = app_context['load_settings']()
        token = get_token(settings)
        if not token:
            return False
        kgs = [{'id': 'default'}]

    started = 0
    with _poll_lock:
        for kg in kgs:
            if kg.get('status') != 'active':
                continue
            kg_id = kg['id']
            s = app_context['load_settings'](kg_id)
            token = get_token(s)
            if not token:
                continue
            # Check if thread already exists for this kg_id
            thread_name = f'telegram-poll-{kg_id}'
            existing = any(
                t.name == thread_name and t.is_alive()
                for t in threading.enumerate()
            )
            if existing:
                started += 1
                continue
            t = threading.Thread(
                target=run_polling,
                args=(app_context, kg_id),
                daemon=True,
                name=thread_name
            )
            t.start()
            started += 1
    return started > 0


def get_webhook_info(token):
    return tg_call(token, 'getWebhookInfo')


# ─── Super admin / Support bot ──────────────────────────────────────────────
SUPER_BOT_CHAT_ID = None
RESET_SESSIONS = {}  # chat_id -> {step, phone, otp, otp_expiry, admin_type, admin_data, kg_id}
AUTH_SESSIONS = {}  # chat_id -> {kg_id, kg_name, name, phone, role, step}

def auth_keyboard():
    return {'keyboard': [[{'text': '📊 Monitoring'}, {'text': '💳 To\'lov'}],[{'text': '📩 Shikoyat'}],[{'text': '🚪 Chiqish'}]],'resize_keyboard': True}

def start_keyboard():
    return {'keyboard': [[{'text': '🔑 Kirish'}],[{'text': '🔐 Parolni tiklash'}]],'resize_keyboard': True,'one_time_keyboard': True}

def _get_kg_name(kg_id, app_context):
    """Get kindergarten name from its id."""
    pc = app_context.get('pc') if app_context else None
    if pc and kg_id:
        for kg in pc.load_kindergartens():
            if kg.get('id') == kg_id:
                return kg.get('name', '')
    return ''

def _find_admin_by_phone(phone, app_context):
    """Find admin by phone. Returns (type, data, kg_id) or None."""
    pc = app_context.get('pc')
    if not pc:
        return None
    for sa in pc.load_json('super_admins.json'):
        if sa.get('login') == phone:
            return ('super', sa, None)
    for kg in pc.load_kindergartens():
        owner = kg.get('owner', {})
        if owner.get('login') == phone:
            return ('kg_admin', owner, kg.get('id'))
    for a in pc.load_json('admins.json', 'default'):
        if a.get('login') == phone:
            return ('legacy', a, 'default')
    return None

def _is_phone_likely(text):
    cleaned = re.sub(r'[\s\-\(\)\+]', '', text)
    return cleaned.isdigit() and 7 <= len(cleaned) <= 15

def _clean_phone(text):
    return re.sub(r'[\s\-\(\)\+]', '', text)

def super_bot_polling(token, authorized_chat_id, app_context=None):
    """Super bot — parolni tiklash va super admin xabarlari."""
    global SUPER_BOT_CHAT_ID
    SUPER_BOT_CHAT_ID = str(authorized_chat_id)
    tg_call(token, 'deleteWebhook', drop_pending_updates=False)
    print(f"[SuperBot] Polling boshlandi (chat: {authorized_chat_id})")
    offset = 0
    while True:
        try:
            data = tg_call(token, 'getUpdates', offset=offset, timeout=25)
            if not data.get('ok'):
                time.sleep(3)
                continue
            for upd in data.get('result', []):
                offset = upd['update_id'] + 1
                message = upd.get('message')
                if not message:
                    continue
                chat_id = str(message['chat']['id'])
                text = (message.get('text') or '').strip()
                contact = message.get('contact')
                first_name = message['chat'].get('first_name', 'Foydalanuvchi')
                _handle_super_message(token, chat_id, text, first_name, authorized_chat_id, app_context, contact)
        except Exception as ex:
            print(f"[SuperBot] xato: {ex}")
            time.sleep(4)

def _handle_super_message(token, chat_id, text, first_name, authorized_chat_id, app_context, contact=None):
    # Handle phone number shared via contact button
    if contact:
        phone_raw = contact.get('phone_number', '')
        if phone_raw:
            text = phone_raw

    is_super = (chat_id == authorized_chat_id)
    lower = text.strip().lower()

    # ── Super admin commands ──
    if is_super:
        if lower in ('/start', '/help', 'start', 'boshlash', 'salom'):
            BASE_URL = 'https://sofgardercrm.vercel.app'
            # Generate public stats token
            pub_token = os.environ.get('PUBLIC_STATS_TOKEN', '').strip()
            if not pub_token:
                sk = os.environ.get('SECRET_KEY', 'sofgarder2024')
                pub_token = hashlib.sha256(sk.encode()).hexdigest()[:16]
            pub_url = f'{BASE_URL}/public/stats?token={pub_token}'
            kb = {'inline_keyboard': [
                [{'text': '🔐 Platformaga kirish', 'url': f'{BASE_URL}/login'}],
                [{'text': '📊 Statistika', 'url': f'{BASE_URL}/super/stats'}],
                [{'text': '📋 Kirish tarixi', 'url': f'{BASE_URL}/super/login-history'}],
                [{'text': '📈 Kunlik tahlil', 'url': f'{BASE_URL}/super/daily-stats'}],
                [{'text': '🔗 Maxsus stats link', 'url': pub_url}],
            ]}
            return send_message(token, chat_id,
                f"👋 Assalomu alaykum, <b>{first_name}</b>!\n\n"
                f"Bu <b>EduSoft</b> platformasi uchun maxsus bot.\n"
                f"Quyidagi tugmalar orqali tezkor kirishingiz mumkin:",
                reply_markup=kb)
        if lower in ('/stats', 'statistika', '📊 statistika'):
            kb = {'inline_keyboard': [
                [{'text': '📊 1 kun', 'callback_data': 'super_stats_1d'}],
                [{'text': '📊 1 hafta', 'callback_data': 'super_stats_1w'}],
                [{'text': '📊 1 oy', 'callback_data': 'super_stats_1m'}],
                [{'text': '📊 1 yil', 'callback_data': 'super_stats_1y'}],
            ]}
            BASE_URL = 'https://sofgardercrm.vercel.app'
            return send_message(token, chat_id,
                f"📊 <b>Statistika</b>\n\n"
                f"Davrni tanlang yoki to'liq statistika uchun havola:\n"
                f"🌐 <a href='{BASE_URL}/super/stats'>Web-statistika</a>",
                reply_markup=kb)

    # ── Authenticated user menu ──
    auth = AUTH_SESSIONS.get(chat_id)
    if auth and not auth.get('step'):
        if text == '📊 Monitoring':
            kg_id = auth['kg_id']
            try:
                pc = (app_context or {}).get('pc')
                students = pc.load_json('students.json', kg_id) if pc else []
                active = [s for s in students if s.get('status') == 'active']
                att = pc.load_json('attendance.json', kg_id) if pc else []
                today = datetime.now().strftime('%Y-%m-%d')
                td = [a for a in att if a.get('date') == today]
                pr = sum(1 for a in td if a['status'] == 'present')
                pays = pc.load_json('payments.json', kg_id) if pc else []
                pending = [p for p in pays if p.get('status') == 'pending']
                send_message(token, chat_id,
                    f"📊 <b>Monitoring</b>\n\n"
                    f"👨‍🎓 Faol o'quvchilar: <b>{len(active)}</b>\n"
                    f"📅 Bugun: <b>{pr}/{len(td)}</b> ({round(pr/len(td)*100) if td else 0}%)\n"
                    f"⏳ Kutilayotgan to'lovlar: <b>{len(pending)}</b>\n"
                    f"🏫 {esc(auth['kg_name'])}",
                    reply_markup=auth_keyboard())
            except Exception:
                send_message(token, chat_id, "❌ Ma'lumot yuklanmadi.")
            return
        if text == '💳 To\'lov':
            kg_id = auth['kg_id']
            try:
                pc = (app_context or {}).get('pc')
                settings = pc.load_settings(kg_id) if pc else {}
                balance = settings.get('balance', 0)
                parent_name = auth.get('name', '')
                parent_phone = auth.get('phone', '')
                import urllib.parse
                params = urllib.parse.urlencode({'name': parent_name, 'phone': parent_phone})
                pay_url = f"{BASE_URL}/tezcheck-pay/{kg_id}?{params}"
                # Get last 5 payments
                payments = pc.load_payments(kg_id) if pc else []
                recent = [p for p in payments if p.get('parent_name') == parent_name or p.get('parent_phone') == parent_phone][-5:]
                msg = (
                    f"💳 <b>To'lov</b>\n\n"
                    f"🏫 {esc(auth['kg_name'])}\n"
                    f"💰 Joriy balans: <b>{balance:,}</b> so'm\n\n"
                )
                if recent:
                    msg += "📋 <b>Oxirgi to'lovlaringiz:</b>\n"
                    for p in reversed(recent):
                        status_icon = '✅' if p.get('status') == 'paid' else '⏳'
                        msg += f"{status_icon} {p['amount']:,} so'm — {p.get('status', 'kutilmoqda')}\n"
                    msg += "\n"
                msg += (
                     f"To'lov qilish uchun quyidagi havolani bosing:\n"
                     f"🔗 <a href='{pay_url}'>To'lov sahifasi</a>"
                )
                kb = {'inline_keyboard': [[{'text': '💳 To\'lov qilish', 'url': pay_url}]]}
                send_message(token, chat_id, msg, reply_markup=kb)
            except Exception:
                send_message(token, chat_id, "❌ Xatolik yuz berdi.")
            return
        if text == '📩 Shikoyat':
            AUTH_SESSIONS[chat_id]['step'] = 'await_complaint'
            send_message(token, chat_id,
                "📝 <b>Shikoyat yoki ariza</b>\n\n"
                "Matningizni yuboring. Super admin tekshiradi.\n"
                "Bekor qilish uchun /cancel",
                reply_markup=remove_keyboard())
            return
        if text == '🚪 Chiqish':
            AUTH_SESSIONS.pop(chat_id, None)
            send_message(token, chat_id, "✅ Tizimdan chiqdingiz. /start", reply_markup=remove_keyboard())
            return
        send_message(token, chat_id, f"👋 <b>{esc(auth['name'])}</b>\n🏫 {esc(auth['kg_name'])}", reply_markup=auth_keyboard())
        return

    # ── Login flow (phone → password → authenticate) ──
    if auth and auth.get('step') == 'await_complaint':
        AUTH_SESSIONS.pop(chat_id, None)
        pc = (app_context or {}).get('pc')
        plat = pc.load_platform() if pc else {}
        st = plat.get('super_bot_token', '').strip()
        sc = plat.get('super_telegram_chat_id', '').strip()
        if st and sc:
            send_message(st, sc,
                f"📩 <b>Shikoyat</b>\n\n"
                f"👤 {esc(auth['name'])}\n🏫 {esc(auth['kg_name'])}\n📞 {esc(auth['phone'])}\n\n{esc(text)}")
        send_message(token, chat_id, "✅ Shikoyatingiz qabul qilindi.", reply_markup=remove_keyboard())
        msg = f"👋 <b>{esc(auth['name'])}</b>\n🏫 {esc(auth['kg_name'])}"
        send_message(token, chat_id, msg, reply_markup=auth_keyboard())
        return

    if auth and auth.get('step') == 'await_login_pass':
        password = text
        pc = (app_context or {}).get('pc')
        if pc:
            phone_raw = auth['phone']
            norm_fn = (app_context or {}).get('normalize_phone')
            # Try multiple formats: raw, normalized, last 9 digits
            candidates = [phone_raw]
            if norm_fn:
                n = norm_fn(phone_raw)
                if n and n != phone_raw:
                    candidates.append(n)
            tail = phone_raw[-9:] if len(phone_raw) >= 9 else phone_raw
            if tail not in candidates:
                candidates.append(tail)
            for candidate in candidates:
                result = pc.authenticate(candidate, password)
                if result:
                    kg_id = result.get('kindergarten_id', '')
                    kg_name = _get_kg_name(kg_id, app_context) if kg_id else ''
                    AUTH_SESSIONS[chat_id] = {'kg_id': kg_id, 'kg_name': kg_name, 'name': result['name'], 'phone': candidate, 'role': result['role']}
                    send_message(token, chat_id, f"✅ Xush kelibsiz, <b>{esc(result['name'])}</b>!", reply_markup=auth_keyboard())
                    return
        AUTH_SESSIONS.pop(chat_id, None)
        send_message(token, chat_id, "❌ Login yoki parol noto'g'ri. Qaytadan /start", reply_markup=remove_keyboard())
        return

    # ── Forgot-password conversation ──
    session = RESET_SESSIONS.get(chat_id, {})
    step = session.get('step', 'idle')

    # Cancel any active flow
    if lower in ('/cancel', 'bekor qilish', 'ortga'):
        RESET_SESSIONS.pop(chat_id, None)
        AUTH_SESSIONS.pop(chat_id, None)
        return send_message(token, chat_id, "✅ Bekor qilindi. Yangi buyruqni kiriting.")

    # ── Help/welcome for non-super ──
    if lower in ('/start', '/help', 'start', 'boshlash', 'salom', 'yordam'):
        RESET_SESSIONS.pop(chat_id, None)
        AUTH_SESSIONS.pop(chat_id, None)
        msg = (
            f"👋 Assalomu alaykum, <b>{first_name}</b>!\n\n"
            f"Bu <b>EduSoft</b> — o'quv markaz boshqaruv tizimining yordamchi boti.\n\n"
            f"🔑 <b>Kirish</b> — login va parol orqali bog'changizni boshqaring\n"
            f"🔐 <b>Parolni tiklash</b> — parolni unutgan bo'lsangiz"
        )
        return send_message(token, chat_id, msg, reply_markup=start_keyboard())

    # ── Handle button selections ──
    if text == '🔑 Kirish':
        AUTH_SESSIONS[chat_id] = {'step': 'await_login_phone', 'phone': ''}
        return send_message(token, chat_id,
            "📞 <b>Login</b> (telefon raqam) ni yuboring.\n"
            "Masalan: <code>998993190712</code>\n"
            "Bekor qilish uchun /cancel",
            reply_markup=phone_keyboard())
    if text == '🔐 Parolni tiklash':
        # Fall through to existing forgot-password /start flow
        RESET_SESSIONS.pop(chat_id, None)
        # Check if user already linked phone via a kindergarten bot
        existing_phone = None
        existing_name = None
        try:
            get_session = (app_context or {}).get('get_bot_session')
            if get_session:
                sess = get_session(chat_id)
                if sess and sess.get('step') == 'linked' and sess.get('phone'):
                    sp = sess['phone']
                    result = _find_admin_by_phone(sp, app_context)
                    if result:
                        existing_phone = sp
                        existing_name = result[1].get('name', first_name)
                        existing_kg_id = result[2]
        except Exception:
            pass

        if existing_phone:
            kg_label = ''
            kg_id = existing_kg_id
            if kg_id:
                kg_name = _get_kg_name(kg_id, app_context)
                if kg_name:
                    kg_label = f"🏫 <b>{esc(kg_name)}</b>\n"
            msg = (
                f"👋 Assalomu alaykum, <b>{esc(existing_name)}</b>!\n\n"
                f"{kg_label}"
                f"📞 <code>{existing_phone}</code>\n\n"
                f"🔑 Parolni tiklash uchun <b>ha</b> deb yozing yoki "
                f"boshqa raqam yuboring.\n"
                f"❌ Bekor qilish uchun /cancel"
            )
            RESET_SESSIONS[chat_id] = {
                'step': 'confirm_phone',
                'phone': existing_phone,
            }
        else:
            msg = (
                f"👋 <b>Parolni tiklash</b>\n\n"
                f"Telefon raqamingizni yuboring "
                f"(masalan: <code>998996272562</code>).\n"
                f"Biz raqamni tekshirib, parolni tiklash kodini yuboramiz."
            )
        return send_message(token, chat_id, msg, reply_markup=phone_keyboard())

    # ── Login flow: await phone ──
    auth_login = AUTH_SESSIONS.get(chat_id)
    if auth_login and auth_login.get('step') == 'await_login_phone':
        phone_raw = ''
        if contact:
            phone_raw = contact.get('phone_number', '')
            text = phone_raw
        elif _is_phone_likely(text):
            phone_raw = _clean_phone(text)
        if not phone_raw:
            return send_message(token, chat_id, "❌ Telefon raqam yuboring. Masalan: <code>998901234567</code>")
        if len(phone_raw) < 9:
            return send_message(token, chat_id, "❌ Raqam juda qisqa. Masalan: <code>998901234567</code>")
        AUTH_SESSIONS[chat_id] = {'step': 'await_login_pass', 'phone': phone_raw}
        return send_message(token, chat_id,
            "🔑 <b>Parolni</b> kiriting.\nBekor qilish uchun /cancel",
            reply_markup=remove_keyboard())

    # ── Step: confirm_phone (user was recognized from bot session) ──
    if step == 'confirm_phone':
        if lower in ('ha', 'yes', 'haa', 'xop'):
            phone = session.get('phone', '')
            result = _find_admin_by_phone(phone, app_context)
            if not result:
                RESET_SESSIONS.pop(chat_id, None)
                return send_message(token, chat_id,
                    f"❌ <b>{phone}</b> raqami tizimda topilmadi.\n"
                    f"Iltimos, raqamingizni qayta yuboring.")
            admin_type, admin_data, kg_id = result
            otp = ''.join(random.choices('0123456789', k=6))
            expiry = (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()
            RESET_SESSIONS[chat_id] = {
                'step': 'otp_sent',
                'phone': phone,
                'otp': otp,
                'otp_expiry': expiry,
                'admin_type': admin_type,
                'admin_data': admin_data,
                'kg_id': kg_id,
            }
            return send_message(token, chat_id,
                f"🔐 <b>Parolni tiklash kodi:</b>\n\n"
                f"<b>{otp}</b>\n\n"
                f"Kodni shu yerga yozib yuboring. 5 daqiqa amal qiladi.\n"
                f"Bekor qilish uchun /cancel",
                reply_markup=remove_keyboard())
        elif lower in ('/cancel', 'bekor', 'yo\'q', 'no'):
            RESET_SESSIONS.pop(chat_id, None)
            return send_message(token, chat_id, "✅ Bekor qilindi. Yangi raqam yuboring yoki /start")
        else:
            # Treat as a new phone number
            pass

    # ── Step 1: Phone received ──
    if step == 'idle' and _is_phone_likely(text):
        phone = _clean_phone(text)

        # Check phone exists in the system
        result = _find_admin_by_phone(phone, app_context)
        if not result:
            msg = (
                f"❌ <b>{phone}</b> raqami tizimda topilmadi.\n\n"
                f"Bu raqam bilan bog'langan admin hisobi mavjud emas.\n\n"
                f"📝 Ro'yxatdan o'tish uchun bog'changiz botiga murojaat qiling:\n"
                f"👉 <a href='https://t.me/ytt_yangiavlod_robot'>@ytt_yangiavlod_robot</a>"
            )
            # If not super, suggest linking via bot session
            if not is_super:
                try:
                    get_session = (app_context or {}).get('get_bot_session')
                    if get_session:
                        sess = get_session(chat_id)
                        if sess and sess.get('step') == 'linked' and sess.get('phone'):
                            linked_phone = sess['phone']
                            msg += (
                                f"\n\n💡 Profilingizdagi raqam: <code>{esc(linked_phone)}</code>\n"
                                f"Aynan shu raqamni yuboring."
                            )
                except Exception:
                    pass
            return send_message(token, chat_id, msg)

        admin_type, admin_data, kg_id = result
        otp = ''.join(random.choices('0123456789', k=6))
        expiry = (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()

        RESET_SESSIONS[chat_id] = {
            'step': 'otp_sent',
            'phone': phone,
            'otp': otp,
            'otp_expiry': expiry,
            'admin_type': admin_type,
            'admin_data': admin_data,
            'kg_id': kg_id,
        }

        send_message(token, chat_id,
            f"📞 <b>Raqam tasdiqlandi!</b>\n\n"
            f"<code>{phone}</code> raqami "
            f"<b>{esc(admin_data.get('name', 'Admin'))}</b> "
            f"hisobiga tegishli.\n"
            f"{'🏫 Bog\'cha: <b>' + esc(_get_kg_name(kg_id, app_context)) + '</b>' if kg_id else ''}\n\n"
            f"🔐 <b>Parolni tiklash kodi:</b>\n\n"
            f"<b>{otp}</b>\n\n"
            f"Kodni shu yerga yozib yuboring. Kod 5 daqiqa amal qiladi.\n"
            f"Bekor qilish uchun /cancel",
            reply_markup=remove_keyboard())

        # Also notify super admin
        if is_super:
            send_message(token, chat_id,
                f"🔐 <b>Parolni tiklash</b>\n\n"
                f"Admin: {esc(admin_data.get('name', 'Admin'))}\n"
                f"Telefon: {phone}\n"
                f"Kod: {otp}\n"
                f"✅ Bot orqali amalga oshirilmoqda.")
        else:
            pc = (app_context or {}).get('pc')
            if pc:
                plat = pc.load_platform()
                s_token = plat.get('super_bot_token', '').strip()
                s_chat = plat.get('super_telegram_chat_id', '').strip()
                if s_token and s_chat and s_chat != chat_id:
                    send_message(s_token, s_chat,
                        f"🔐 <b>Parolni tiklash so'rovi</b>\n\n"
                        f"Foydalanuvchi: {esc(first_name)}\n"
                        f"Telefon: {phone}\n"
                        f"Admin: {esc(admin_data.get('name', 'Admin'))}\n"
                        f"Kod: {otp}")
        return

    # ── Step 2: OTP verification ──
    if step == 'otp_sent':
        otp_input = text.strip()
        sess = RESET_SESSIONS[chat_id]

        if datetime.now(timezone.utc).timestamp() > sess['otp_expiry']:
            RESET_SESSIONS.pop(chat_id, None)
            return send_message(token, chat_id,
                "❌ Kod muddati tugagan. Iltimos, telefon raqamingizni qayta yuboring.")

        if otp_input != sess['otp']:
            return send_message(token, chat_id,
                f"❌ Noto'g'ri kod. Qaytadan urinib ko'ring yoki bekor qilish uchun /cancel")

        # OTP verified — ask for new password
        sess['step'] = 'otp_verified'
        return send_message(token, chat_id,
            f"✅ <b>Kod tasdiqlandi!</b>\n\n"
            f"Endi <b>yangi parol</b>ni yuboring.\n\n"
            f"📋 Talablar:\n"
            f"• Kamida 8 ta belgi\n"
            f"• Kamida 1 ta katta harf (A-Z)\n"
            f"• Kamida 1 ta raqam (0-9)\n\n"
            f"Misol: <code>NewPass1</code>\n"
            f"Bekor qilish uchun /cancel")

    # ── Step 3: New password received ──
    if step == 'otp_verified':
        errors = []
        if len(text) < 8:
            errors.append('Kamida 8 ta belgi')
        if not re.search(r'[A-Z]', text):
            errors.append('Kamida 1 ta katta harf')
        if not re.search(r'[0-9]', text):
            errors.append('Kamida 1 ta raqam')
        if errors:
            return send_message(token, chat_id,
                f"❌ Parol talablarga javob bermadi:\n"
                f"{chr(10).join('• '+e for e in errors)}\n\n"
                f"Qaytadan urinib ko'ring yoki /cancel")

        sess = RESET_SESSIONS[chat_id]
        new_password = text
        hashed = hashlib.sha256(new_password.encode()).hexdigest()
        phone = sess['phone']
        admin_type = sess['admin_type']
        admin_data = sess['admin_data']
        kg_id = sess['kg_id']
        pc = (app_context or {}).get('pc')

        if not pc:
            return send_message(token, chat_id, "❌ Tizim xatosi. Keyinroq urinib ko'ring.")

        if admin_type == 'super':
            supers = pc.load_json('super_admins.json')
            for s in supers:
                if s.get('id') == admin_data.get('id'):
                    s['password'] = hashed
                    break
            pc.save_json('super_admins.json', supers)

        elif admin_type == 'kg_admin':
            kgs = pc.load_kindergartens()
            for kg in kgs:
                owner = kg.get('owner', {})
                if owner.get('login') == phone:
                    kg['owner']['password'] = hashed
                    break
            pc.save_kindergartens(kgs)

        elif admin_type == 'legacy':
            legacy = pc.load_json('admins.json', 'default')
            for a in legacy:
                if a.get('login') == phone:
                    a['password'] = hashed
                    break
            pc.save_json('admins.json', legacy, 'default')

        RESET_SESSIONS.pop(chat_id, None)

        admin_name = admin_data.get('name', 'Admin')

        # Notify super admin
        plat = pc.load_platform()
        s_token = plat.get('super_bot_token', '').strip()
        s_chat = plat.get('super_telegram_chat_id', '').strip()
        if s_token and s_chat and s_chat != chat_id:
            send_message(s_token, s_chat,
                f"🔑 <b>Parol o'zgartirildi</b>\n\n"
                f"Admin: {esc(admin_name)}\n"
                f"Telefon: {phone}\n"
                f"Foydalanuvchi: {esc(first_name)}\n"
                f"Vaqt: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                f"Agar admin tomonidan amalga oshirilmagan bo'lsa, tekshiring!")

        return send_message(token, chat_id,
            f"✅ <b>Parolingiz muvaffaqiyatli o'zgartirildi!</b>\n\n"
            f"Admin: {esc(admin_name)}\n"
            f"Telefon: {phone}\n\n"
            f"Endi <a href='https://t.me/EduSoft_Support_bot'>saytga kirish</a> "
            f"uchun yangi parolingizdan foydalanishingiz mumkin.\n\n"
            f"Agar siz qilmagan bo'lsangiz, "
            f"darhol @mr_turaqulov ga bog'laning.")

    # ── Unknown input ──
    if _is_phone_likely(text):
        phone = _clean_phone(text)
        if not is_super:
            linked_phone = None
            try:
                get_session = (app_context or {}).get('get_bot_session')
                if get_session:
                    sess = get_session(chat_id)
                    if sess and sess.get('step') == 'linked' and sess.get('phone'):
                        linked_phone = sess['phone']
            except Exception:
                pass
            if not linked_phone:
                return send_message(token, chat_id,
                    f"❌ Siz hali hech qanday bog'chada ro'yxatdan o'tmagansiz.\n\n"
                    f"Avval bog'changizning Telegram boti orqali "
                    f"telefon raqamingizni ulashing.\n\n"
                    f"🆘 Yordam: @mr_turaqulov")
            if phone != linked_phone:
                return send_message(token, chat_id,
                    f"❌ Bu raqam sizning profilingizga bog'lanmagan.\n"
                    f"Sizning raqamingiz: <code>{esc(linked_phone)}</code>\n"
                    f"Aynan shu raqamni yuboring.")
        result = _find_admin_by_phone(phone, app_context)
        if not result:
            return send_message(token, chat_id,
                f"❌ <b>{phone}</b> raqami tizimda topilmadi.")
    else:
        return send_message(token, chat_id,
            f"❌ Tushunarsiz buyruq.\n\n"
            f"📞 Parolni tiklash uchun telefon raqamingizni yuboring.\n"
            f"🆘 Yordam uchun /help")

def _generate_super_stats_text(period_days, label, app_context):
    try:
        from app import audit_log, pc
        logs = audit_log.get_logs(pc, days=period_days, limit=5000)
        # Filter login-related events
        login_logs = [l for l in logs if l.get('action') in ('login', 'logout', 'failed_login', 'super_admin_blocked_ip')]
        # Stats
        total_logins = sum(1 for l in login_logs if l['action'] == 'login')
        total_failed = sum(1 for l in login_logs if l['action'] == 'failed_login')
        total_logouts = sum(1 for l in login_logs if l['action'] == 'logout')
        total_blocked = sum(1 for l in login_logs if l['action'] == 'super_admin_blocked_ip')
        # Unique IPs
        all_ips = set(l.get('ip', '') for l in login_logs if l.get('ip'))
        # Who logged in — unique admin names
        admins = {}
        for l in login_logs:
            if l['action'] == 'login':
                aname = l.get('admin_name') or l.get('admin') or 'Noma\'lum'
                ip = l.get('ip', '?')
                ts = (l.get('timestamp') or '?')[:19]
                if aname not in admins:
                    admins[aname] = {'count': 0, 'last': ts, 'ip': ip}
                admins[aname]['count'] += 1
                if ts > admins[aname]['last']:
                    admins[aname]['last'] = ts
                    admins[aname]['ip'] = ip
        # Build message
        lines = [
            f"📊 <b>Statistika ({label})</b>",
            f"",
            f"👥 <b>Kirishlar:</b>",
            f"✅ Muvaffaqiyatli: {total_logins}",
            f"❌ Muvaffaqiyatsiz: {total_failed}",
            f"🚪 Chiqish: {total_logouts}",
            f"🚫 Bloklangan IP: {total_blocked}",
            f"🌐 Unikal IP: {len(all_ips)} ta",
            f"",
        ]
        if admins:
            lines.append("👤 <b>Kirgan adminlar:</b>")
            for aname, info in sorted(admins.items(), key=lambda x: -x[1]['count']):
                lines.append(f"  • <b>{esc(aname)}</b> — {info['count']} marta")
                lines.append(f"    🕐 Oxirgi: {info['last']}, 🌐 {info['ip']}")
            lines.append("")
        lines.append(f"📅 Davr: {label}")
        BASE_URL = 'https://sofgardercrm.vercel.app'
        lines.append(f"🌐 <a href='{BASE_URL}/super/stats'>To'liq statistika</a>")
        lines.append(f"📋 <a href='{BASE_URL}/super/login-history'>Kirish tarixi</a>")
        return '\n'.join(lines)
    except Exception as e:
        print(f"[ERROR] _generate_super_stats_text: {e}")
        return "❌ Statistika yuklanmadi."

def _handle_super_callback(cb, token, authorized_chat_id, app_context):
    data = cb.get('data', '')
    cb_id = cb['id']
    chat_id = str(cb['message']['chat']['id'])
    msg_id = cb['message']['message_id']
    if chat_id != authorized_chat_id:
        tg_call(token, 'answerCallbackQuery', callback_query_id=cb_id,
            text="Siz super admin emassiz.")
        return
    period_map = {
        'super_stats_1d': (1, '1 kun'),
        'super_stats_1w': (7, '1 hafta'),
        'super_stats_1m': (30, '1 oy'),
        'super_stats_1y': (365, '1 yil'),
    }
    if data in period_map:
        days, label = period_map[data]
        tg_call(token, 'answerCallbackQuery', callback_query_id=cb_id,
            text=f"⏳ {label} statistikasi yuklanmoqda...")
        text = _generate_super_stats_text(days, label, app_context)
        try:
            tg_call(token, 'editMessageText',
                chat_id=chat_id, message_id=msg_id,
                text=text, parse_mode='HTML')
        except Exception:
            send_message(token, chat_id, text)
    else:
        tg_call(token, 'answerCallbackQuery', callback_query_id=cb_id)

def handle_super_update(update, plat, app_context=None):
    """Super bot webhook update handler (Vercel)."""
    token = (plat or {}).get('super_bot_token', '').strip()
    chat = (plat or {}).get('super_telegram_chat_id', '').strip()
    if not token:
        return
    # Handle callback queries
    cb = update.get('callback_query')
    if cb:
        _handle_super_callback(cb, token, chat, app_context)
        return
    message = update.get('message') or update.get('edited_message')
    if not message:
        return
    chat_id = str(message['chat']['id'])
    text = (message.get('text') or '').strip()
    contact = message.get('contact')
    first_name = message['chat'].get('first_name', 'Foydalanuvchi')
    _handle_super_message(token, chat_id, text, first_name, chat, app_context, contact)
