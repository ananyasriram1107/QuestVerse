"""
Which browser origins may call the API.

FRONTEND_URL holds the deployed frontend's origin (for example https://questverse.vercel.app); several
can be given, comma separated, e.g. for a custom domain plus a Vercel preview. Entries must be a full
http(s) origin with no path -- "*" and malformed values are ignored (and logged), never accepted.
Local development origins (the Vite dev and preview servers) are added unless QUESTVERSE_ENV is
"production", so a production deployment only trusts the origins it was configured with.
"""

import logging
import re
from typing import Optional

log = logging.getLogger(__name__)

DEV_ORIGINS = [
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://localhost:5174", "http://127.0.0.1:5174",
    "http://localhost:4173", "http://127.0.0.1:4173",
]
_ORIGIN_RE = re.compile(r"^https?://[A-Za-z0-9.-]+(:\d{1,5})?$")


def allowed_origins(frontend_url: Optional[str], environment: str = "development") -> list:
    origins: list = []
    for raw in (frontend_url or "").split(","):
        origin = raw.strip().rstrip("/")
        if not origin:
            continue
        if not _ORIGIN_RE.match(origin):
            log.warning("Ignoring FRONTEND_URL entry %r: expected an origin like https://app.example.com", raw)
            continue
        origins.append(origin)
    if environment.lower() != "production":
        origins += DEV_ORIGINS
    elif not origins:
        log.warning("QUESTVERSE_ENV=production but FRONTEND_URL has no valid origin: browsers will be refused by CORS.")
    return list(dict.fromkeys(origins))
