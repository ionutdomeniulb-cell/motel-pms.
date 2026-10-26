"""Ceasul aplicației. Normal = ora Windows. Cu MOTEL_TEST_NOW="AAAA-LL-ZZ HH:MM" pornește de la acea oră și curge normal
(ceas de test: nu atinge ora PC-ului; pe toate paginile apare banda „CEAS DE TEST”)."""
import os
from datetime import datetime, timedelta

_offset = timedelta(0)
_active = False


def configure(value=None):
    """Setează ceasul de test (sau îl oprește cu None/"")."""
    global _offset, _active
    value = (value if value is not None else os.environ.get("MOTEL_TEST_NOW", "")).strip()
    if not value:
        _offset, _active = timedelta(0), False
        return
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            target = datetime.strptime(value, fmt)
            break
        except ValueError:
            continue
    else:
        raise SystemExit(f"MOTEL_TEST_NOW invalid: {value!r}. Format: AAAA-LL-ZZ HH:MM")
    _offset, _active = target - datetime.now(), True


def now():
    return datetime.now() + _offset


def today():
    return now().date()


def is_test():
    return _active


configure()
