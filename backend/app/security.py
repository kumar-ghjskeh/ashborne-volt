"""HTTP hardening for the public API.

The browser reads jobs from static files; this service only does the few things
that need a server (résumé parsing and matching, prompt assembly, Gemini calls,
PDF compile, push subscriptions). Everything else in main.py is legacy from the
database era and must not be reachable from the internet, so:

* **Allowlist.** Only the routes in PUBLIC_ROUTES answer; any other path is a
  404, whatever main.py happens to define. Adding a public endpoint is a
  deliberate edit here, never a side effect of adding a route.
* **Rate limits** per client IP on everything that costs money or CPU (the
  Gemini key, the PDF compiler, résumé parsing).
* **Body-size cap** before a request body is read.
* **Security headers** on every response.

State is in-process memory: the free instance runs one worker, and a restart
resetting the counters is acceptable for abuse protection of this kind.
"""

from __future__ import annotations

import re
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# (method, path regex) pairs the public may call.
PUBLIC_ROUTES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (m, re.compile(p)) for m, p in (
        ("GET", r"^/health$"),
        ("GET", r"^/push/public-key$"),
        ("POST", r"^/push/subscribe$"),
        ("POST", r"^/resume/parse$"),
        ("POST", r"^/resume/match$"),
        ("POST", r"^/resume-studio/tailor-prompt$"),
        ("POST", r"^/resume-studio/interview-prompt$"),
        ("POST", r"^/resume-studio/tailor/generate$"),
        ("POST", r"^/resume-studio/interview/generate$"),
        ("POST", r"^/resume-studio/compile-pdf$"),
    )
)

# path regex -> (max requests, window seconds). First match wins.
RATE_LIMITS: tuple[tuple[re.Pattern[str], int, int], ...] = tuple(
    (re.compile(p), n, w) for p, n, w in (
        (r"/generate$", 12, 3600),          # spends the Gemini key
        (r"^/resume-studio/compile-pdf$", 20, 3600),
        (r"^/resume/parse$", 30, 3600),
        (r"^/push/subscribe$", 10, 3600),
        (r"^/resume/match$", 240, 3600),
        (r".*", 600, 3600),                 # everything else
    )
)

MAX_BODY_BYTES = 10 * 1024 * 1024  # an 8 MB résumé plus multipart overhead

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cache-Control": "no-store",
}


def is_public(method: str, path: str) -> bool:
    if method == "OPTIONS":            # CORS preflight; CORSMiddleware answers it
        return True
    return any(m == method and rx.match(path) for m, rx in PUBLIC_ROUTES)


def client_ip(request: Request) -> str:
    # Render terminates TLS and appends the client to X-Forwarded-For; the first
    # entry is the original client.
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def allow(self, ip: str, path: str, now: float | None = None) -> tuple[bool, int]:
        now = now if now is not None else time.monotonic()
        for rx, limit, window in RATE_LIMITS:
            if rx.search(path):
                key = (ip, rx.pattern)
                q = self._hits[key]
                while q and q[0] <= now - window:
                    q.popleft()
                if len(q) >= limit:
                    return False, int(window - (now - q[0])) + 1
                q.append(now)
                return True, 0
        return True, 0


class HardeningMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: RateLimiter | None = None, enforce_allowlist: bool = True):
        super().__init__(app)
        self.limiter = limiter or RateLimiter()
        self.enforce_allowlist = enforce_allowlist

    async def dispatch(self, request: Request, call_next):
        method, path = request.method.upper(), request.url.path
        if self.enforce_allowlist and not is_public(method, path):
            return self._headers(JSONResponse({"detail": "Not Found"}, status_code=404))

        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
            return self._headers(JSONResponse({"detail": "Request too large"}, status_code=413))

        if method != "OPTIONS":
            ok, retry = self.limiter.allow(client_ip(request), path)
            if not ok:
                resp = JSONResponse({"detail": "Too many requests — please try again later."},
                                    status_code=429)
                resp.headers["Retry-After"] = str(retry)
                return self._headers(resp)

        return self._headers(await call_next(request))

    @staticmethod
    def _headers(resp: Response) -> Response:
        for k, v in SECURITY_HEADERS.items():
            resp.headers.setdefault(k, v)
        return resp


# Production origin plus Vercel preview deployments of THIS project only. The
# inherited regex trusted every *.vercel.app site on the internet.
VERCEL_PREVIEW_ORIGIN = r"https://ashborne-volt(-[a-z0-9-]+)?\.vercel\.app"
