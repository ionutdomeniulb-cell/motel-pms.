"""Versiunea aplicației (afișată discret în subsol)."""
VERSION = "17"
REVISION = "1"
BUILD_DATE = "2026-10-26"


def label():
    y, m, d = BUILD_DATE.split("-")
    return f"v{VERSION} · r{REVISION} · {d}.{m}.{y}"
