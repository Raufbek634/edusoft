"""Audit log — readonly, append-only, tamper-evident log system."""
import json
import os
import hashlib
from datetime import datetime, timedelta


AUDIT_FILE = 'audit_logs.json'


def _get_logs_path(pc):
    return os.path.join(pc.data_dir, AUDIT_FILE)


def _load_logs(pc):
    path = _get_logs_path(pc)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []
    db_logs = pc.load_json(AUDIT_FILE)
    if isinstance(db_logs, list):
        return db_logs
    return []


def _save_logs(pc, logs):
    path = _get_logs_path(pc)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)
    try:
        pc.save_json(AUDIT_FILE, logs)
    except Exception:
        pass


def log(pc, action, details='', admin_id='', admin_name='', kg_id='', ip=''):
    """Append an immutable audit log entry."""
    logs = _load_logs(pc)
    prev_hash = logs[-1]['hash'] if logs else ''
    entry = {
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'action': action,
        'details': details,
        'admin_id': admin_id,
        'admin_name': admin_name,
        'kg_id': kg_id,
        'ip': ip,
    }
    raw = json.dumps(entry, sort_keys=True, ensure_ascii=False)
    entry['hash'] = hashlib.sha256(f"{prev_hash}{raw}".encode()).hexdigest()
    logs.append(entry)
    _save_logs(pc, logs)
    return entry


def verify_chain(pc):
    """Verify all log entries form an unbroken hash chain. Returns (ok, first_broken_index)."""
    logs = _load_logs(pc)
    prev_hash = ''
    for i, entry in enumerate(logs):
        raw = json.dumps({k: v for k, v in entry.items() if k != 'hash'}, sort_keys=True, ensure_ascii=False)
        expected = hashlib.sha256(f"{prev_hash}{raw}".encode()).hexdigest()
        if entry.get('hash') != expected:
            return False, i
        prev_hash = entry['hash']
    return True, -1


def get_logs(pc, kg_id=None, action=None, admin_id=None, days=None, limit=500):
    """Query logs with filters. Returns newest first."""
    logs = _load_logs(pc)
    if days:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat() + 'Z'
        logs = [e for e in logs if e.get('timestamp', '') >= cutoff]
    if kg_id:
        logs = [e for e in logs if e.get('kg_id') == kg_id]
    if action:
        logs = [e for e in logs if e.get('action', '').startswith(action)]
    if admin_id:
        logs = [e for e in logs if e.get('admin_id') == admin_id]
    logs.sort(key=lambda e: e.get('timestamp', ''), reverse=True)
    return logs[:limit]


def weekly_report(pc):
    """Generate a weekly summary text for Telegram."""
    logs = _load_logs(pc)
    week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat() + 'Z'
    week_logs = [e for e in logs if e.get('timestamp', '') >= week_ago]
    summary = {}
    for e in week_logs:
        act = e.get('action', 'unknown')
        summary[act] = summary.get(act, 0) + 1
    lines = [f"📋 <b>Haftalik audit hisobot</b>", f"🗓 {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC", ""]
    lines.append(f"Jami hodisalar: {len(week_logs)}")
    lines.append("")
    for act, count in sorted(summary.items(), key=lambda x: -x[1]):
        lines.append(f"  {act}: {count}")
    lines.append("")
    # Suspicious
    suspicious = []
    for e in week_logs:
        if e.get('action') in ('payment_deleted', 'attendance_bulk_edit'):
            suspicious.append(f"  ⚠️ {e.get('action')} — {e.get('admin_name')} ({e.get('timestamp')[:10]})")
    if suspicious:
        lines.append("⚠️ <b>Shubhali harakatlar:</b>")
        lines.extend(suspicious)
    else:
        lines.append("✅ Shubhali harakat yo'q")
    return '\n'.join(lines)


def check_suspicious(pc, action, details='', **kw):
    """Returns True if the action is considered suspicious."""
    low = details.lower()
    # Existing checks
    if action == 'payment_deleted':
        if 'hours_ago' in details:
            try:
                h = int(details.split('hours_ago:')[1].split()[0])
                if h >= 24:
                    return True
            except Exception:
                pass
    if action == 'attendance_bulk_edit':
        return True
    # SQL injection attempts
    if action == 'failed_login':
        sql_patterns = ["' or", "1=1", "admin'--", "select", "union", "drop ", "delete ", "insert ", "exec ", "xp_"]
        if any(p in low for p in sql_patterns):
            return True
    # Path traversal attempts
    if action in ('page_view', 'file_access'):
        if '../' in low or '..\\' in low or '%2e%2e' in low:
            return True
    # Blocked IP attempts
    if action == 'super_admin_blocked_ip':
        return True
    return False
