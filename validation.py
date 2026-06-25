"""Input validation helpers — Z7 API protection."""

import re


PHONE_RE = re.compile(r'^998\d{9}$')
NAME_RE = re.compile(r"^[a-zA-Z\u00C0-\u024F\u0400-\u04FF\s'-]+$")
UUID4_RE = re.compile(r'^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$', re.I)


def validate_phone(val):
    return bool(val and PHONE_RE.match(val.strip()))


def validate_name(val, min_len=2, max_len=50):
    if not val or not isinstance(val, str):
        return False
    v = val.strip()
    return min_len <= len(v) <= max_len and bool(NAME_RE.match(v))


def validate_amount(val):
    try:
        return int(val) >= 0 if val is not None else False
    except (ValueError, TypeError):
        return False


def validate_date(val):
    if not val or not isinstance(val, str):
        return False
    import datetime
    try:
        datetime.date.fromisoformat(val)
        return True
    except ValueError:
        return False


def validate_month(val):
    if not val or not isinstance(val, str):
        return False
    import re as _re
    return bool(_re.match(r'^\d{4}-\d{2}$', val))


def sanitize_html(val):
    """Strip HTML tags from user input to prevent XSS."""
    import re as _re
    if not val or not isinstance(val, str):
        return val
    return _re.sub(r'<[^>]*>', '', val)
