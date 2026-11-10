"""Application logging. Credentials embedded in URLs are always redacted."""

import logging
import sys

from src import config
from src.security import redact


class RedactingFilter(logging.Filter):
    def filter(self, record):
        if record.args:
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        return True


_configured = False


def configure_logging():
    global _configured
    if _configured:
        return
    _configured = True
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(config.LOG_LEVEL)
    # Uvicorn access logs include query strings only (never credentials),
    # but route them through the same filter for consistency.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).addFilter(RedactingFilter())
