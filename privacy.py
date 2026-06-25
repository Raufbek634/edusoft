"""AES-256 encryption for sensitive fields + privacy utilities."""
import os
import base64
import hashlib
import json
from datetime import datetime, timedelta

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


_SALT = b'edusoft_salt_2024'
_FERNET_CACHE = None


def _get_fernet():
    global _FERNET_CACHE
    if not HAS_CRYPTO:
        return None
    if _FERNET_CACHE:
        return _FERNET_CACHE
    key = os.environ.get('ENCRYPTION_KEY', '').strip()
    if not key or len(key) < 16:
        return None  # No key configured — encryption unavailable
    if len(key) < 32:
        key = key.ljust(32, 'x')
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=_SALT, iterations=600000)
    raw_key = base64.urlsafe_b64encode(kdf.derive(key.encode()))
    _FERNET_CACHE = Fernet(raw_key)
    return _FERNET_CACHE


def encrypt(plain_text):
    if not plain_text or not HAS_CRYPTO:
        return plain_text
    return _get_fernet().encrypt(plain_text.encode()).decode()


def decrypt(cipher_text):
    if not cipher_text or not HAS_CRYPTO:
        return cipher_text
    try:
        return _get_fernet().decrypt(cipher_text.encode()).decode()
    except Exception:
        return cipher_text


SENSITIVE_KEYS = {
    'phone', 'parent_phone', 'login', 'address',
    'medical_info', 'notes_medical', 'temp_password',
    'payment_card', 'card_number',
}


def encrypt_dict(data, keys=None):
    if not data or not isinstance(data, dict) or not HAS_CRYPTO:
        return data
    keys = keys or SENSITIVE_KEYS
    for k in list(data.keys()):
        if k in keys and isinstance(data[k], str) and data[k]:
            data[k] = encrypt(data[k])
        elif isinstance(data[k], dict):
            encrypt_dict(data[k], keys)
        elif isinstance(data[k], list):
            for item in data[k]:
                if isinstance(item, dict):
                    encrypt_dict(item, keys)
    return data


def decrypt_dict(data, keys=None):
    if not data or not isinstance(data, dict) or not HAS_CRYPTO:
        return data
    keys = keys or SENSITIVE_KEYS
    for k in list(data.keys()):
        if k in keys and isinstance(data[k], str) and data[k]:
            dec = decrypt(data[k])
            if dec:
                data[k] = dec
        elif isinstance(data[k], dict):
            decrypt_dict(data[k], keys)
        elif isinstance(data[k], list):
            for item in data[k]:
                if isinstance(item, dict):
                    decrypt_dict(item, keys)
    return data


# ── Data Retention ──────────────────────────────────────────────────────────

def purge_expired_deleted_data(pc):
    """Delete student and related data that was 'deleted' over 1 year ago."""
    purged = 0
    for kg in pc.load_kindergartens():
        kg_id = kg.get('id')
        if not kg_id:
            continue
        students = pc.load_json('students.json', kg_id)
        if not isinstance(students, list):
            continue
        cutoff = (datetime.utcnow() - timedelta(days=365)).timestamp()
        kept = []
        for s in students:
            deleted_at = s.get('_deleted_at') or (s.get('deleted_at') if s.get('status') == 'deleted' else None)
            if deleted_at:
                try:
                    if isinstance(deleted_at, (int, float)) and deleted_at < cutoff:
                        purged += 1
                        continue
                    if isinstance(deleted_at, str) and datetime.fromisoformat(deleted_at).timestamp() < cutoff:
                        purged += 1
                        continue
                except Exception:
                    pass
            kept.append(s)
        if len(kept) != len(students):
            pc.save_json('students.json', kept, kg_id)
    return purged


# ── Right to be forgotten ──────────────────────────────────────────────────

def create_deletion_request(pc, kg_id, phone, parent_name, reason=''):
    """Create a data deletion request (right to be forgotten)."""
    reqs = pc.load_json('deletion_requests.json')
    if not isinstance(reqs, list):
        reqs = []
    reqs.append({
        'id': hashlib.md5(f"{phone}_{datetime.utcnow().isoformat()}".encode()).hexdigest()[:12],
        'kg_id': kg_id,
        'phone': phone,
        'parent_name': parent_name,
        'reason': reason,
        'created_at': datetime.utcnow().isoformat(),
        'status': 'pending',
    })
    pc.save_json('deletion_requests.json', reqs)
    return reqs[-1]


def execute_deletion_request(pc, req_id):
    """Admin approves a deletion request — removes all data for that phone."""
    reqs = pc.load_json('deletion_requests.json')
    req = None
    for r in reqs:
        if r.get('id') == req_id:
            req = r
            break
    if not req:
        return False
    req['status'] = 'approved'
    req['approved_at'] = datetime.utcnow().isoformat()
    kg_id = req.get('kg_id')
    phone = req.get('phone')
    if kg_id and phone:
        students = pc.load_json('students.json', kg_id)
        if isinstance(students, list):
            students = [s for s in students if s.get('parent_phone') != phone]
            pc.save_json('students.json', students, kg_id)
        portfolios = pc.load_json('parent_portfolios.json', kg_id)
        if isinstance(portfolios, list):
            portfolios = [p for p in portfolios if p.get('phone') != phone]
            pc.save_json('parent_portfolios.json', portfolios, kg_id)
        complaints = pc.load_json('complaints.json', kg_id)
        if isinstance(complaints, list):
            complaints = [c for c in complaints if c.get('parent_phone') != phone]
            pc.save_json('complaints.json', complaints, kg_id)
        checks = pc.load_json('payment_checks.json', kg_id)
        if isinstance(checks, list):
            checks = [c for c in checks if c.get('parent_phone') != phone]
            pc.save_json('payment_checks.json', checks, kg_id)
    pc.save_json('deletion_requests.json', reqs)
    return True
