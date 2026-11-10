"""
Password hashing, session tokens, secret encryption and credential redaction.

* Passwords: scrypt (Python standard library), per-password random salt.
* Sessions: 256-bit random tokens; only their SHA-256 is stored.
* Camera passwords: Fernet (AES-128-CBC + HMAC-SHA256) with a key derived
  from PARKSIGHT_SECRET_KEY, or from a key file generated on first start.
"""

import base64
import hashlib
import hmac
import logging
import os
import re
import secrets
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from cryptography.fernet import Fernet, InvalidToken

from src import config


log = logging.getLogger(__name__)

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32

MIN_PASSWORD_LENGTH = 10


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def hash_password(password):
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N,
        _SCRYPT_R,
        _SCRYPT_P,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def verify_password(password, stored):
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.b64decode(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# A hash of a random password, used to spend the same time on unknown
# usernames as on known ones (avoids username enumeration by timing).
DUMMY_PASSWORD_HASH = hash_password(secrets.token_hex(16))


def password_problem(password):
    """Return a human-readable reason a password is too weak, or None."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if password.lower() == password or password.upper() == password:
        if not any(ch.isdigit() for ch in password):
            return "Use a mix of upper/lower case letters or include digits."
    return None


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------

def new_token():
    return secrets.token_urlsafe(32)


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Secret encryption (camera passwords)
# ---------------------------------------------------------------------------

_fernet = None


def _load_key_material():
    if config.SECRET_KEY:
        return config.SECRET_KEY.encode("utf-8")
    key_file = config.DATA_DIR / "secret.key"
    if key_file.exists():
        return key_file.read_bytes().strip()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    material = secrets.token_urlsafe(48).encode("ascii")
    # O_EXCL: never overwrite an existing key (that would make stored
    # camera passwords undecryptable).
    fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(material)
    log.warning(
        "Generated a new secret key at %s. Back this file up together with "
        "the database, or set PARKSIGHT_SECRET_KEY.",
        key_file,
    )
    return material


def _get_fernet():
    global _fernet
    if _fernet is None:
        material = _load_key_material()
        derived = hashlib.sha256(b"parksight-fernet-v1:" + material).digest()
        _fernet = Fernet(base64.urlsafe_b64encode(derived))
    return _fernet


def encrypt_secret(value):
    if value is None or value == "":
        return None
    return _get_fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(token):
    if not token:
        return None
    try:
        return _get_fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        log.error(
            "A stored camera password could not be decrypted. The secret key "
            "has changed; re-enter the camera password."
        )
        return None


# ---------------------------------------------------------------------------
# URL credential handling
# ---------------------------------------------------------------------------

_CREDENTIALS_IN_URL = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)[^/@\s]+@")


def redact(text):
    """Remove `user:password@` from any URL inside a string."""
    if not text:
        return text
    return _CREDENTIALS_IN_URL.sub(r"\g<scheme>***@", str(text))


def split_credentials(url):
    """Split `rtsp://user:pass@host/path` into (clean_url, user, password)."""
    parts = urlsplit(url)
    username = parts.username
    password = parts.password
    if username is None and password is None:
        return url, None, None
    host = parts.hostname or ""
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    if parts.port:
        host = f"{host}:{parts.port}"
    clean = urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))
    return (
        clean,
        unquote(username) if username else None,
        unquote(password) if password else None,
    )


def build_stream_url(clean_url, username, password):
    """Insert credentials into a credential-free URL (in memory only)."""
    if not username:
        return clean_url
    parts = urlsplit(clean_url)
    userinfo = quote(username, safe="")
    if password:
        userinfo += ":" + quote(password, safe="")
    return urlunsplit(
        (parts.scheme, f"{userinfo}@{parts.netloc}", parts.path, parts.query, parts.fragment)
    )
