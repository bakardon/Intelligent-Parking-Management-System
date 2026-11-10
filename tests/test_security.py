"""Password hashing, credential redaction and secret encryption."""

from src import security
from src.auth import LoginThrottle


def test_password_hash_roundtrip():
    stored = security.hash_password("Correct-horse-1")
    assert stored.startswith("scrypt$")
    assert "Correct-horse-1" not in stored
    assert security.verify_password("Correct-horse-1", stored)
    assert not security.verify_password("wrong", stored)
    assert not security.verify_password("x", "garbage")


def test_hashes_are_salted():
    assert security.hash_password("same-Password1") != security.hash_password("same-Password1")


def test_password_policy():
    assert security.password_problem("short")
    assert security.password_problem("alllowercaseletters")
    assert security.password_problem("Long-enough-Pass1") is None


def test_redact_removes_credentials():
    text = "failed to open rtsp://admin:s3cret@10.0.0.5:554/stream1 (timeout)"
    redacted = security.redact(text)
    assert "s3cret" not in redacted and "admin" not in redacted
    assert "rtsp://***@10.0.0.5:554/stream1" in redacted


def test_split_and_build_credentials():
    clean, user, password = security.split_credentials("rtsp://op%40site:p%3Ass@192.168.1.20:554/h264")
    assert clean == "rtsp://192.168.1.20:554/h264"
    assert (user, password) == ("op@site", "p:ss")
    rebuilt = security.build_stream_url(clean, user, password)
    assert security.split_credentials(rebuilt) == (clean, user, password)
    assert security.split_credentials("rtsp://cam/stream") == ("rtsp://cam/stream", None, None)


def test_secret_encryption_roundtrip():
    token = security.encrypt_secret("camera-pass")
    assert token and "camera-pass" not in token
    assert security.decrypt_secret(token) == "camera-pass"
    assert security.encrypt_secret("") is None
    assert security.decrypt_secret("not-a-token") is None


def test_login_throttle():
    throttle = LoginThrottle(max_failures=3, window=60)
    for _ in range(3):
        assert not throttle.blocked("ip:1")
        throttle.failure("ip:1")
    assert throttle.blocked("ip:1")
    assert not throttle.blocked("ip:2")
    throttle.success("ip:1")
    assert not throttle.blocked("ip:1")
