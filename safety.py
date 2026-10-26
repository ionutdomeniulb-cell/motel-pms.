"""Funcții de securitate fără dependență de Flask (testabile separat)."""
import re
from urllib.parse import urlsplit

WEAK_PINS = {"123456", "654321", "12345678", "87654321", "123123", "112233", "121212", "159753", "147258", "258369", "111222",
             "123321", "101010", "696969", "789456", "456789", "987654", "147852", "1234567", "7654321", "12341234", "11223344"}
PHONE_RE = re.compile(r"[0-9+()\-\s./]{3,40}")
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def pin_is_weak(pin):
    """PIN-uri ușor de ghicit: cifre repetate, serii crescătoare/descrescătoare, jumătăți identice, liste uzuale."""
    if not pin:
        return True
    if len(set(pin)) == 1 or pin in WEAK_PINS:
        return True
    steps = {int(b) - int(a) for a, b in zip(pin, pin[1:])}
    if steps in ({1}, {-1}):
        return True
    half = len(pin) // 2
    return len(pin) % 2 == 0 and pin[:half] == pin[half:]


def pin_message(pin):
    if not (pin.isdigit() and 6 <= len(pin) <= 8):
        return "PIN-ul trebuie să aibă 6–8 cifre."
    return "PIN prea ușor de ghicit (serii precum 123456, cifre repetate). Alegeți altul."


def pin_valid(pin):
    return pin.isdigit() and 6 <= len(pin) <= 8 and not pin_is_weak(pin)


def csv_safe(value):
    """Neutralizează injecția de formule în CSV/Excel: celulele care încep cu = + - @ sunt prefixate cu apostrof."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def safe_next(target, default):
    """Acceptă doar căi locale; refuză //host, \\host, scheme și caractere de control (open redirect)."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target or any(ord(c) < 32 for c in target):
        return default
    parts = urlsplit(target)
    if parts.scheme or parts.netloc:
        return default
    return target
