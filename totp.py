"""Autentificare în 2 pași (TOTP, RFC 6238): coduri de 6 cifre, valabile 30 s, compatibile cu Google/Microsoft Authenticator."""
import base64
import hashlib
import hmac
import secrets
import struct
import urllib.parse

STEP, DIGITS, WINDOW = 30, 6, 1


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _key(secret):
    padded = secret.upper() + "=" * (-len(secret) % 8)
    return base64.b32decode(padded)


def code_at(secret, step):
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def verify(secret, code, unix_time, last_step=None):
    """Întoarce pasul de timp folosit (pentru a refuza reutilizarea codului) sau None."""
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(code) != DIGITS or not secret:
        return None
    current = int(unix_time // STEP)
    for step in range(current - WINDOW, current + WINDOW + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def provisioning_uri(secret, username, issuer="PMS Popas Caprioara"):
    label = urllib.parse.quote(f"{issuer}:{username}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={urllib.parse.quote(issuer)}&digits={DIGITS}&period={STEP}"


def grouped(secret):
    return " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))


def new_recovery_codes(count=8):
    return [f"{secrets.randbelow(10**4):04d}-{secrets.randbelow(10**4):04d}" for _ in range(count)]
