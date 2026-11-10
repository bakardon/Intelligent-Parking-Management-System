"""
Local access control.

* Sessions: random token in an HttpOnly, SameSite=Strict cookie; only the
  token's SHA-256 is stored server-side.
* CSRF: state-changing requests must carry `X-Requested-With: ParkSight`.
  Browsers cannot add custom headers to cross-site requests without a CORS
  pre-flight, which ParkSight never approves.
* Brute force: failed logins are throttled per client address and per
  username.
"""

import secrets
import threading
import time

from fastapi import Depends, HTTPException, Request, status

from src import config


SESSION_COOKIE = "parksight_session"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "ParkSight"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

MAX_FAILURES = 5
FAILURE_WINDOW_SECONDS = 15 * 60


class LoginThrottle:
    def __init__(self, max_failures=MAX_FAILURES, window=FAILURE_WINDOW_SECONDS):
        self.max_failures = max_failures
        self.window = window
        self._failures = {}
        self._lock = threading.Lock()

    def _recent(self, key, now):
        attempts = [t for t in self._failures.get(key, []) if now - t < self.window]
        self._failures[key] = attempts
        return attempts

    def blocked(self, *keys):
        now = time.monotonic()
        with self._lock:
            return any(len(self._recent(k, now)) >= self.max_failures for k in keys)

    def failure(self, *keys):
        now = time.monotonic()
        with self._lock:
            for key in keys:
                self._recent(key, now).append(now)

    def success(self, *keys):
        with self._lock:
            for key in keys:
                self._failures.pop(key, None)


class SetupToken:
    """One-time token required to create the first administrator.

    Printed to the server log at start-up while no user exists, so only
    someone with access to the server console/logs can claim the install.
    """

    def __init__(self):
        self.value = None

    def issue(self):
        self.value = secrets.token_urlsafe(18)
        return self.value

    def check(self, candidate):
        return self.value is not None and secrets.compare_digest(self.value, candidate.strip())

    def consume(self):
        self.value = None


def client_key(request):
    return f"ip:{request.client.host if request.client else 'unknown'}"


def set_session_cookie(response, token, expires):
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=config.SESSION_HOURS * 3600,
        expires=expires,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="strict",
        path="/",
    )


def clear_session_cookie(response):
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="strict", httponly=True,
                           secure=config.COOKIE_SECURE)


def check_csrf(request: Request):
    if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing or invalid request header")


def current_user(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required")
    user = request.app.state.repos.user_for_session(token)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired; sign in again")
    check_csrf(request)
    return user


def require_admin(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required")
    return user
