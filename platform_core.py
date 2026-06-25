"""Platform: super admin, ko'p bog'cha, obuna, eslatmalar."""
import json
import os
import hashlib
import uuid
import shutil
import time
from datetime import datetime, date, timedelta, timezone
from functools import wraps

PLATFORM_FILES = {
    'platform.json', 'super_admins.json', 'kindergartens.json',
    'kindergarten_applications.json', 'platform_announcements.json'
}

DEFAULT_PLATFORM = {
    "monthly_price_usd": 10,
    "trial_days": 30,
    "grace_days": 30,
    "currency_label": "USD",
    "super_telegram_chat_id": "6439945348",
    "super_bot_token": "",
    "platform_channels": [],
    "plans": [
        {"id": "standard", "name": "Standart", "price_usd": 10, "trial_days": 30,
         "desc": "1 oy bepul, keyin oyiga $10 — barcha asosiy funksiyalar"},
        {"id": "premium", "name": "Premium", "price_usd": 25, "trial_days": 30,
         "desc": "Telegram bot, avtomatik to'lov eslatmalari, prioritet qo'llab-quvvatlash"}
    ],
    "tezcheck_shop_id": "",
    "tezcheck_shop_key": "",
    "checkout_api_key": "",
    "payment_api_provider": "tezcheck"
}


def hash_password(pw):
    from werkzeug.security import generate_password_hash
    return generate_password_hash(pw)

def verify_password(plain, hashed):
    if not hashed or not plain:
        return False
    from werkzeug.security import check_password_hash
    try:
        if check_password_hash(hashed, plain):
            return True
    except (ValueError, TypeError):
        pass
    return hashlib.sha256(plain.encode()).hexdigest() == hashed


class FileLock:
    """Cross-platform file lock using a sibling .lock file."""

    def __init__(self, path, timeout=5):
        self.lock_path = path + '.lock'
        self.timeout = timeout
        self._fd = None

    def __enter__(self):
        deadline = time.time() + self.timeout
        while True:
            try:
                self._fd = os.open(self.lock_path, os.O_CREAT | os.O_WRONLY | os.O_EXCL)
                return self
            except OSError:
                if time.time() > deadline:
                    raise TimeoutError(f'Could not acquire lock: {self.lock_path}')
                time.sleep(0.05)

    def __exit__(self, *args):
        if self._fd is not None:
            os.close(self._fd)
            try:
                os.unlink(self.lock_path)
            except OSError:
                pass


class PgStore:
    """PostgreSQL JSON storage (shared across serverless instances)."""

    def __init__(self, url=None):
        self.url = url or os.environ.get('DATABASE_URL')
        self._conn = None

    def _connect(self):
        if self._conn is None or self._conn.closed:
            import psycopg2
            import urllib.parse
            parsed = urllib.parse.urlparse(self.url)
            qs = urllib.parse.parse_qs(parsed.query)
            sslmode = qs.get('sslmode', ['disable'])[0]
            self._conn = psycopg2.connect(self.url, sslmode=sslmode)
            self._conn.autocommit = True
            with self._conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS jsondata (
                        key TEXT PRIMARY KEY,
                        value JSONB NOT NULL
                    )
                """)
        return self._conn

    def get(self, key):
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute('SELECT value FROM jsondata WHERE key = %s', (key,))
            row = cur.fetchone()
            return row[0] if row else None

    def set(self, key, data):
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO jsondata (key, value) VALUES (%s, %s) '
                'ON CONFLICT (key) DO UPDATE SET value = %s',
                (key, json.dumps(data), json.dumps(data))
            )

    def exists(self, key):
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute('SELECT 1 FROM jsondata WHERE key = %s', (key,))
            return cur.fetchone() is not None

    def list_keys(self, prefix=''):
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute('SELECT key FROM jsondata WHERE key LIKE %s', (prefix + '%',))
            return [row[0] for row in cur.fetchall()]

    def delete_key(self, key):
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute('DELETE FROM jsondata WHERE key = %s', (key,))


class PlatformCtx:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.db = None
        db_url = (os.environ.get('DATABASE_URL')
                  or os.environ.get('POSTGRES_URL')
                  or os.environ.get('POSTGRES_URL_NON_POOLING')
                  or os.environ.get('STORAGE_URL')
                  or os.environ.get('STORAGE_URL_NON_POOLING'))
        if db_url:
            self.db = PgStore(db_url)

    def _path(self, filename, kg_id=None):
        if filename in PLATFORM_FILES:
            return os.path.join(self.data_dir, filename)
        kid = kg_id or 'default'
        base = os.path.join(self.data_dir, 'tenants', kid)
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, filename)

    def _db_key(self, filename, kg_id=None):
        if filename in PLATFORM_FILES:
            return filename
        kid = kg_id or 'default'
        return f'tenants/{kid}/{filename}'

    def _seed_to_db(self):
        """Upload all local data files to PostgreSQL — only if key doesn't exist."""
        for fn in PLATFORM_FILES:
            if self.db.exists(fn):
                continue
            fp = os.path.join(self.data_dir, fn)
            if os.path.exists(fp):
                with open(fp, 'r', encoding='utf-8') as f:
                    try:
                        data = json.load(f)
                    except Exception:
                        data = []
                self.db.set(fn, data)
        tenant_root = os.path.join(self.data_dir, 'tenants')
        if os.path.isdir(tenant_root):
            for d in os.listdir(tenant_root):
                tdir = os.path.join(tenant_root, d)
                if not os.path.isdir(tdir):
                    continue
                for fn in os.listdir(tdir):
                    fp = os.path.join(tdir, fn)
                    if os.path.isfile(fp) and fn.endswith('.json'):
                        key = self._db_key(fn, d)
                        if self.db.exists(key):
                            continue
                        with open(fp, 'r', encoding='utf-8') as f:
                            try:
                                data = json.load(f)
                            except Exception:
                                data = [] if fn != 'settings.json' else {}
                        self.db.set(key, data)

    def load_json(self, filename, kg_id=None):
        if self.db:
            key = self._db_key(filename, kg_id)
            data = self.db.get(key)
            if data is not None:
                if filename not in PLATFORM_FILES and filename != 'settings.json' and isinstance(data, dict):
                    data = [data]
                return data
            return []
        path = self._path(filename, kg_id)
        if not os.path.exists(path):
            if kg_id in (None, 'default') and filename not in PLATFORM_FILES:
                legacy = os.path.join(self.data_dir, filename)
                if os.path.exists(legacy):
                    with open(legacy, 'r', encoding='utf-8') as f:
                        try:
                            data = json.load(f)
                            if filename != 'settings.json' and isinstance(data, dict):
                                data = [data]
                            return data
                        except Exception:
                            return []
            return []
        with open(path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                if filename not in PLATFORM_FILES and filename != 'settings.json' and isinstance(data, dict):
                    data = [data]
                return data
            except Exception:
                return []

    def save_json(self, filename, data, kg_id=None):
        if self.db:
            key = self._db_key(filename, kg_id)
            return self.db.set(key, data)
        path = self._path(filename, kg_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with FileLock(path, timeout=5):
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
        except (TimeoutError, OSError):
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def load_platform(self):
        p = self.load_json('platform.json')
        if not p:
            p = DEFAULT_PLATFORM.copy()
            self.save_json('platform.json', p)
        for k, v in DEFAULT_PLATFORM.items():
            if k not in p:
                p[k] = v
        if os.environ.get('SUPER_BOT_TOKEN'):
            p['super_bot_token'] = os.environ['SUPER_BOT_TOKEN']
        if os.environ.get('SUPER_TELEGRAM_CHAT_ID'):
            p['super_telegram_chat_id'] = os.environ['SUPER_TELEGRAM_CHAT_ID']
        if os.environ.get('TEZCHECK_SHOP_ID'):
            p['tezcheck_shop_id'] = os.environ['TEZCHECK_SHOP_ID']
        if os.environ.get('TEZCHECK_SHOP_KEY'):
            p['tezcheck_shop_key'] = os.environ['TEZCHECK_SHOP_KEY']
        if os.environ.get('CHECKOUT_API_KEY'):
            p['checkout_api_key'] = os.environ['CHECKOUT_API_KEY']
            if os.environ.get('PAYMENT_API_PROVIDER', 'tezcheck') == 'checkout':
                p['payment_api_provider'] = 'checkout'
        return p

    def load_kindergartens(self):
        return self.load_json('kindergartens.json')

    def save_kindergartens(self, data):
        self.save_json('kindergartens.json', data)

    def get_kindergarten(self, kg_id):
        for kg in self.load_kindergartens():
            if kg['id'] == kg_id:
                return kg
        return None

    def load_settings(self, kg_id):
        s = self.load_json('settings.json', kg_id)
        if not isinstance(s, dict):
            s = {}
        default = {
            "name": "Mening bog'cham", "currency": "UZS", "bot_token": "",
            "admin_telegram_chat_id": "", "bot_username": "",
            "tagline": "Farzandingiz uchun xavfsiz va quvnoq muhit",
            "required_channels": [], "logo": "",
            "payment_card": "",
            "payment_provider": "manual_card",
            "payment_merchant_id": "",
            "payment_service_id": "",
            "balance": 0,
            "auto_payment": True
        }
        for k, v in default.items():
            if k not in s:
                s[k] = v
        # Populate admin_login from the kindergarten owner data
        kg = self.get_kindergarten(kg_id)
        if kg:
            owner = kg.get('owner', {})
            s['admin_login'] = owner.get('login', '')
        elif 'admin_login' not in s:
            s['admin_login'] = ''
        # Merge platform channels with kindergarten channels
        plat = self.load_platform()
        platform_chs = plat.get('platform_channels', [])
        kg_channels = s.get('required_channels', [])
        merged = []
        seen = set()
        for ch in platform_chs + kg_channels:
            ch_clean = ch.strip()
            if ch_clean and ch_clean not in seen:
                seen.add(ch_clean)
                merged.append(ch_clean)
        s['required_channels'] = merged
        return s

    def save_settings(self, kg_id, settings):
        self.save_json('settings.json', settings, kg_id)

    def load_payments(self, kg_id):
        return self.load_json('payments.json', kg_id)

    def save_payments(self, kg_id, payments):
        self.save_json('payments.json', payments, kg_id)

    def add_payment(self, kg_id, order_id, amount, parent_name='', parent_phone=''):
        payments = self.load_payments(kg_id)
        rec = {
            'id': 'RCP-' + str(uuid.uuid4())[:8].upper(),
            'order_id': str(order_id),
            'kg_id': kg_id,
            'parent_name': parent_name,
            'parent_phone': parent_phone,
            'amount': amount,
            'status': 'pending',
            'created_at': datetime.now(timezone.utc).isoformat() + 'Z',
            'paid_at': None,
            'transaction_id': None
        }
        payments.append(rec)
        self.save_payments(kg_id, payments)
        return rec

    def update_payment(self, kg_id, order_id, status, paid_at=None, transaction_id=None):
        payments = self.load_payments(kg_id)
        for p in payments:
            if p['order_id'] == str(order_id):
                p['status'] = status
                if paid_at:
                    p['paid_at'] = paid_at
                if transaction_id:
                    p['transaction_id'] = transaction_id
                break
        self.save_payments(kg_id, payments)

    def load_withdrawals(self, kg_id):
        return self.load_json('withdrawals.json', kg_id)

    def save_withdrawals(self, kg_id, withdrawals):
        self.save_json('withdrawals.json', withdrawals, kg_id)

    def add_withdrawal(self, kg_id, amount, recipient_name='', recipient_phone='', recipient_card=''):
        withdrawals = self.load_withdrawals(kg_id)
        import random
        code = ''.join(random.choices('0123456789ABCDEFGHJKLMNPQRSTUVWXYZ', k=8))
        while any(w['code'] == code for w in withdrawals):
            code = ''.join(random.choices('0123456789ABCDEFGHJKLMNPQRSTUVWXYZ', k=8))
        withdrawals.append({
            'code': code,
            'kg_id': kg_id,
            'amount': amount,
            'recipient_name': recipient_name,
            'recipient_phone': recipient_phone,
            'recipient_card': recipient_card,
            'status': 'pending',
            'created_at': datetime.now(timezone.utc).isoformat() + 'Z',
            'confirmed_at': None,
            'confirmed_by': ''
        })
        self.save_withdrawals(kg_id, withdrawals)
        return withdrawals[-1]

    def confirm_withdrawal(self, kg_id, code):
        withdrawals = self.load_withdrawals(kg_id)
        for w in withdrawals:
            if w['code'] == code and w['status'] == 'pending':
                w['status'] = 'confirmed'
                w['confirmed_at'] = datetime.now(timezone.utc).isoformat() + 'Z'
                self.save_withdrawals(kg_id, withdrawals)
                return w
        return None

    def init_platform_data(self):
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(os.path.join(self.data_dir, 'tenants', 'default'), exist_ok=True)

        if self.db:
            self._seed_to_db()
            return

        if not os.path.exists(os.path.join(self.data_dir, 'super_admins.json')):
            self.save_json('super_admins.json', [{
                "id": "super-1",
                "login": "rauf",
                "password": hash_password("07102012"),
                "name": "Raufbek Turaqulov",
                "role": "platform_owner"
            }])

        self.load_platform()

        for f in PLATFORM_FILES:
            if f == 'platform.json':
                continue
            p = os.path.join(self.data_dir, f)
            if not os.path.exists(p):
                self.save_json(f, [])

        # Default bog'cha
        kgs = self.load_kindergartens()
        if not kgs:
            legacy_settings = {}
            lp = os.path.join(self.data_dir, 'settings.json')
            if os.path.exists(lp):
                with open(lp, 'r', encoding='utf-8') as f:
                    try:
                        legacy_settings = json.load(f)
                    except Exception:
                        pass
            kg = {
                "id": "default",
                "name": legacy_settings.get('name', "Mening bog'cham"),
                "status": "active",
                "plan": "standard",
                "created_at": datetime.now().isoformat(),
                "subscription": {
                    "trial_start": date.today().isoformat(),
                    "trial_days": 30,
                    "monthly_price_usd": 10,
                    "paid_until": None
                },
                "owner": {
                    "login": "993190712",
                    "password": hash_password("12345678"),
                    "name": "Administrator",
                    "telegram_chat_id": legacy_settings.get('admin_telegram_chat_id', '')
                }
            }
            self.save_kindergartens([kg])
            if legacy_settings:
                self.save_settings('default', legacy_settings)

        # Eski fayllarni default tenantga ko'chirish
        tenant_files = [
            'students.json', 'attendance.json', 'payments.json', 'notifications.json',
            'registrations.json', 'complaints.json', 'bot_sessions.json',
            'parent_portfolios.json', 'reminder_log.json'
        ]
        for fn in tenant_files:
            dst = self._path(fn, 'default')
            src = os.path.join(self.data_dir, fn)
            if os.path.exists(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)

    def _record_login(self, kg_id):
        from datetime import datetime
        now = datetime.now(timezone.utc).isoformat() + 'Z'
        kgs = self.load_kindergartens()
        for kg in kgs:
            if kg['id'] == kg_id:
                kg['last_login'] = now
                break
        self.save_kindergartens(kgs)

    def _delete_kindergarten(self, kg_id):
        kgs = self.load_kindergartens()
        kgs = [kg for kg in kgs if kg['id'] != kg_id]
        self.save_kindergartens(kgs)
        # Remove all tenant data from DB
        if self.db:
            prefix = f'tenants/{kg_id}/'
            for key in self.db.list_keys(prefix):
                self.db.delete_key(key)
        tenant_dir = os.path.join(self.data_dir, 'tenants', kg_id)
        if os.path.isdir(tenant_dir):
            shutil.rmtree(tenant_dir)
        # Remove from admins.json if default
        admins = self.load_json('admins.json', 'default')
        if kg_id == 'default':
            self.save_json('admins.json', [], 'default')

    def authenticate(self, login_val, password):
        for sa in self.load_json('super_admins.json'):
            if sa['login'] == login_val and verify_password(password, sa.get('password', '')):
                return {'role': 'super', 'id': sa['id'], 'name': sa['name'], 'kindergarten_id': None}
        for kg in self.load_kindergartens():
            if kg.get('status') not in ('active', 'blocked'):
                continue
            owner = kg.get('owner', {})
            if owner.get('login') == login_val and verify_password(password, owner.get('password', '')):
                if kg.get('status') == 'blocked':
                    return {'role': 'blocked', 'id': kg['id'], 'name': owner.get('name', kg['name']), 'kindergarten_id': kg['id']}
                self._record_login(kg['id'])
                return {
                    'role': 'kg_admin',
                    'id': kg['id'],
                    'name': owner.get('name', kg['name']),
                    'kindergarten_id': kg['id']
                }
            # Check additional admins for this kindergarten
            settings = self.load_settings(kg['id'])
            for aa in settings.get('additional_admins', []):
                if aa.get('login') == login_val and verify_password(password, aa.get('password', '')):
                    if kg.get('status') == 'blocked':
                        return {'role': 'blocked', 'id': kg['id'], 'name': aa.get('name', kg['name']), 'kindergarten_id': kg['id']}
                    self._record_login(kg['id'])
                    return {
                        'role': 'kg_admin',
                        'id': kg['id'],
                        'name': aa.get('name', kg['name']),
                        'kindergarten_id': kg['id']
                    }
        # Eski admins.json
        for a in self.load_json('admins.json', 'default'):
            if a.get('login') == login_val and verify_password(password, a.get('password', '')):
                self._record_login('default')
                return {
                    'role': 'kg_admin',
                    'id': 'default',
                    'name': a.get('name', 'Admin'),
                    'kindergarten_id': 'default'
                }
        # Teacher login — o'qituvchilar faqat o'z guruhlarini boshqaradi
        for kg in self.load_kindergartens():
            if kg.get('status') != 'active':
                continue
            kg_id = kg['id']
            teachers = self.load_json('teachers.json', kg_id)
            for t in teachers:
                if t.get('login') == login_val and verify_password(password, t.get('password', '')):
                    if t.get('status') == 'inactive':
                        continue
                    return {
                        'role': 'teacher',
                        'id': t['id'],
                        'name': t.get('name', 'O\'qituvchi'),
                        'kindergarten_id': kg_id,
                        'teacher_id': t['id']
                    }
        return None

    def subscription_status(self, kg):
        sub = kg.get('subscription', {})
        plat = self.load_platform()
        trial_days = sub.get('trial_days', plat.get('trial_days', 30))
        trial_start = sub.get('trial_start', kg.get('created_at', date.today().isoformat()))[:10]
        try:
            ts = datetime.strptime(trial_start, '%Y-%m-%d').date()
        except Exception:
            ts = date.today()
        trial_end = ts + timedelta(days=trial_days)
        paid_until = sub.get('paid_until')
        today = date.today()
        plan = kg.get('plan', 'standard')
        plans = {p['id']: p for p in plat.get('plans', [])}
        plan_info = plans.get(plan, plans.get('standard', {'price_usd': 10}))

        # Check if blocked
        if kg.get('status') == 'blocked':
            return {
                'phase': 'blocked',
                'days_left': 0,
                'monthly_price_usd': plan_info.get('price_usd', plat.get('monthly_price_usd', 10)),
                'plan_name': plan_info.get('name', 'Standart'),
                'message': '⛔ Bog\'cha bloklangan. Admin bilan bog\'laning: @mr_turaqulov'
            }

        if today <= trial_end:
            days_left = (trial_end - today).days
            return {
                'phase': 'trial',
                'days_left': days_left,
                'trial_end': trial_end.isoformat(),
                'monthly_price_usd': plan_info.get('price_usd', plat.get('monthly_price_usd', 10)),
                'plan_name': plan_info.get('name', 'Standart'),
                'message': f"Bepul sinov davri: {days_left} kun qoldi"
            }
        if paid_until:
            try:
                pu = datetime.strptime(paid_until[:10], '%Y-%m-%d').date()
                if today <= pu:
                    days_left = (pu - today).days
                    return {
                        'phase': 'paid',
                        'days_left': days_left,
                        'paid_until': paid_until,
                        'monthly_price_usd': plan_info.get('price_usd', 10),
                        'plan_name': plan_info.get('name', 'Standart'),
                        'message': f"Obuna faol: {days_left} kun qoldi"
                    }
            except Exception:
                pass
        # Check grace period: 30 days after trial/paid end
        last_active = paid_until[:10] if paid_until else trial_end.isoformat()
        try:
            end_date = datetime.strptime(last_active, '%Y-%m-%d').date()
            days_overdue = (today - end_date).days
            if days_overdue > plat.get('grace_days', 30):
                self.set_kg_status(kg['id'], 'blocked')
                return {
                    'phase': 'blocked',
                    'days_left': 0,
                    'monthly_price_usd': plan_info.get('price_usd', 10),
                    'plan_name': plan_info.get('name', 'Standart'),
                    'message': '⛔ Bog\'cha bloklangan. Admin bilan bog\'laning: @mr_turaqulov'
                }
        except Exception:
            pass
        price = plan_info.get('price_usd', plat.get('monthly_price_usd', 10))
        return {
            'phase': 'payment_required',
            'days_left': 0,
            'monthly_price_usd': price,
            'plan_name': plan_info.get('name', 'Standart'),
            'message': f"Obuna to'lovi kerak: oyiga ${price} — platforma egasi bilan bog'laning"
        }

    def set_kg_status(self, kg_id, status):
        kgs = self.load_kindergartens()
        for i, kg in enumerate(kgs):
            if kg['id'] == kg_id:
                kgs[i]['status'] = status
                self.save_kindergartens(kgs)
                return True
        return False

    def _tezcheck_api_key(self):
        plat = self.load_platform()
        return plat.get('tezcheck_shop_key') or plat.get('tezcheck_shop_id') or ''

    def create_invoice(self, amount, description='', kg_id=None, parent_name='', parent_phone=''):
        plat = self.load_platform()
        provider = plat.get('payment_api_provider', 'tezcheck')
        if provider == 'checkout':
            result = self._checkout_create_payment(amount, description)
        else:
            result = self._tezcheck_create_invoice(amount)
        if result and result.get('ok') and result.get('order_id'):
            self.add_payment(kg_id, result['order_id'], amount, parent_name, parent_phone)
        return result

    def check_invoice(self, order_id):
        plat = self.load_platform()
        provider = plat.get('payment_api_provider', 'tezcheck')
        if provider == 'checkout':
            return self._checkout_check_payment(order_id)
        return self._tezcheck_check_invoice(order_id)

    def _checkout_create_payment(self, amount, description=''):
        plat = self.load_platform()
        api_key = plat.get('checkout_api_key', '')
        if not api_key:
            return None
        import urllib.request
        body = json.dumps({"amount": int(amount), "description": description or "EduSoft to'lov"}).encode()
        req = urllib.request.Request(
            'https://checkout.uz/api/v1/create_payment',
            data=body, method='POST')
        req.add_header('Content-Type', 'application/json')
        req.add_header('Authorization', f'Bearer {api_key}')
        req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36')
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                if data.get('status') == 'success' and data.get('payment'):
                    p = data['payment']
                    return {
                        'ok': True,
                        'order_id': p.get('_uuid') or p.get('_id'),
                        'pay_url': p.get('_url'),
                        'payment': p
                    }
        except Exception as e:
            print(f"[Checkout] create_payment error: {e}")
        return None

    def _checkout_check_payment(self, order_id):
        plat = self.load_platform()
        api_key = plat.get('checkout_api_key', '')
        if not api_key:
            return None
        import urllib.request
        body = json.dumps({"uuid": str(order_id)} if len(str(order_id)) > 20 else {"id": int(order_id)}).encode()
        req = urllib.request.Request(
            'https://checkout.uz/api/v1/status_payment',
            data=body, method='POST')
        req.add_header('Content-Type', 'application/json')
        req.add_header('Authorization', f'Bearer {api_key}')
        req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36')
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                if data.get('status') == 'success' and data.get('data'):
                    return {'ok': True, 'payment': data['data']}
        except Exception as e:
            print(f"[Checkout] check_payment error: {e}")
        return None

    def _tezcheck_create_invoice(self, amount, description='', callback_url=''):
        """Create a tezcheck.uz payment invoice. Returns dict with pay_url or None."""
        api_key = self._tezcheck_api_key()
        if not api_key:
            return None
        import urllib.request
        cb_url = callback_url or self._tezcheck_webhook_url()
        body = json.dumps({"api_key": api_key, "amount": int(amount), "callback_url": cb_url}).encode()
        req = urllib.request.Request(
            'https://tezcheck.uz/api/create_invoice',
            data=body, method='POST')
        req.add_header('Content-Type', 'application/json')
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                if data.get('ok'):
                    return data
        except Exception as e:
            print(f"[TezCheck] create_invoice error: {e}")
        return None

    def _tezcheck_check_invoice(self, order_id):
        """Check a tezcheck.uz invoice status. Returns dict with status or None."""
        api_key = self._tezcheck_api_key()
        if not api_key:
            return None
        import urllib.request
        body = json.dumps({"api_key": api_key, "order_id": str(order_id)}).encode()
        req = urllib.request.Request(
            'https://tezcheck.uz/api/status_invoice',
            data=body, method='POST')
        req.add_header('Content-Type', 'application/json')
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                if data.get('ok'):
                    return data
        except Exception as e:
            print(f"[TezCheck] check_invoice error: {e}")
        return None

    def _tezcheck_shop_info(self):
        """Get tezcheck.uz shop balance and info."""
        api_key = self._tezcheck_api_key()
        if not api_key:
            return None
        import urllib.request
        body = json.dumps({"action": "get_shop_info", "api_key": api_key}).encode()
        req = urllib.request.Request(
            'https://tezcheck.uz/api/account',
            data=body, method='POST')
        req.add_header('Content-Type', 'application/json')
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                if data.get('ok'):
                    return data.get('info')
        except Exception as e:
            print(f"[TezCheck] shop_info error: {e}")
        return None

    def _tezcheck_webhook_url(self):
        """Return the TezCheck webhook URL based on deployment environment."""
        import os
        vercel_url = os.environ.get('VERCEL_URL', '')
        if vercel_url:
            return f'https://{vercel_url}/api/tezcheck/webhook'
        return ''

    def get_kg_alerts(self, kg_id, calc_payable_fn, get_paid_fn, get_absent_fn):
        """Bog'cha egasi uchun yuqori bannerlar."""
        kg = self.get_kindergarten(kg_id)
        if not kg:
            return []
        alerts = []
        sub = self.subscription_status(kg)
        if sub['phase'] == 'blocked':
            alerts.append({
                'type': 'danger',
                'icon': '⛔',
                'message': sub.get('message', '⛔ Bog\'cha bloklangan')
            })
            return alerts
        if sub['phase'] == 'trial':
            alerts.append({
                'type': 'info',
                'icon': '🎁',
                'message': f"1 oylik bepul sinov: {sub['days_left']} kun qoldi. Keyin oyiga ${sub['monthly_price_usd']}"
            })
        elif sub['phase'] == 'payment_required':
            alerts.append({
                'type': 'danger',
                'icon': '💳',
                'message': f"💳 To'lov qilish vaqti! Obuna to'lovi kerak: oyiga ${sub['monthly_price_usd']} — platforma egasi bilan bog'laning"
            })
        elif sub['phase'] == 'paid' and sub['days_left'] <= 5:
            alerts.append({
                'type': 'warning',
                'icon': '⏰',
                'message': f"⏰ Obuna {sub['days_left']} kundan keyin tugaydi. Yangilash: ${sub['monthly_price_usd']}/oy"
            })

        students = self.load_json('students.json', kg_id)
        settings = self.load_settings(kg_id)
        today = date.today()
        y, m = today.year, today.month

        for s in students:
            if s.get('status') != 'active':
                continue
            payable = calc_payable_fn(s, y, m)
            paid = get_paid_fn(s['id'], y, m)
            debt = max(payable - paid, 0)
            if debt <= 0:
                continue
            due_day = int(s.get('payment_due_day', 1) or 1)
            try:
                due_date = date(y, m, min(due_day, 28))
                if due_date < today:
                    if m == 12:
                        due_date = date(y + 1, 1, min(due_day, 28))
                    else:
                        due_date = date(y, m + 1, min(due_day, 28))
                days_until = (due_date - today).days
            except Exception:
                days_until = 99
            if 0 <= days_until <= 2:
                alerts.append({
                    'type': 'warning',
                    'icon': '⚠️',
                    'message': f"Qarzdorlik yaqinlashmoqda: {s['first_name']} {s['last_name']} — "
                               f"to'lov sanasi {due_date.strftime('%d.%m')} ({days_until} kun)"
                })
        return alerts[:12]

    def approve_application(self, app_id, apply_logo=None):
        apps = self.load_json('kindergarten_applications.json')
        plat = self.load_platform()
        for i, a in enumerate(apps):
            if a['id'] != app_id:
                continue
            plan_id = a.get('plan', 'standard')
            plans = {p['id']: p for p in plat.get('plans', [])}
            plan = plans.get(plan_id, plans.get('standard', {}))
            kg_id = 'kg-' + str(uuid.uuid4())[:8]
            login_phone = a.get('phone', '')[-9:] or str(uuid.uuid4())[:6]
            kgs = self.load_kindergartens()
            new_kg = {
                "id": kg_id,
                "name": a['kindergarten_name'],
                "status": "active",
                "plan": plan_id,
                "created_at": datetime.now().isoformat(),
                "subscription": {
                    "trial_start": date.today().isoformat(),
                    "trial_days": plan.get('trial_days', 30),
                    "monthly_price_usd": plan.get('price_usd', 10),
                    "paid_until": None
                },
                "owner": {
                    "login": a.get('director_login') or login_phone,
                    "password": hash_password(a.get('temp_password', '12345678')),
                    "name": a['director_name'],
                    "telegram_chat_id": a.get('owner_telegram', '')
                }
            }
            kgs.append(new_kg)
            self.save_kindergartens(kgs)
            settings = {
                "name": a['kindergarten_name'],
                "currency": "UZS",
                "bot_token": "",
                "admin_telegram_chat_id": a.get('owner_telegram', ''),
                "tagline": "",
                "logo": apply_logo or "",
                "required_channels": [],
                "payment_card": "",
                "payment_provider": "manual_card",
                "payment_merchant_id": "",
                "payment_service_id": "",
                "bot_username": "",
                "balance": 0,
                "auto_payment": True
            }
            self.save_settings(kg_id, settings)
            # Initialize tenant data files
            tenant_files = [
                'students.json', 'attendance.json', 'payments.json', 'notifications.json',
                'registrations.json', 'complaints.json', 'bot_sessions.json',
                'parent_portfolios.json', 'reminder_log.json', 'payment_checks.json'
            ]
            for fn in tenant_files:
                self.save_json(fn, [], kg_id)
            apps[i]['status'] = 'approved'
            apps[i]['kindergarten_id'] = kg_id
            self.save_json('kindergarten_applications.json', apps)
            return new_kg, a
        return None, None
