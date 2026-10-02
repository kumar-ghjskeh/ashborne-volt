"""The public API surface: allowlist, CORS, rate limits, size caps, headers."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from backend.app.security import (
    HardeningMiddleware, RateLimiter, VERCEL_PREVIEW_ORIGIN, is_public,
)


def _client(limiter=None):
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/scrape/run-now")
    def run_now():                     # a legacy route that must stay hidden
        return {"started": True}

    @app.post("/resume-studio/tailor/generate")
    def gen():
        return {"latex": "x"}

    app.add_middleware(HardeningMiddleware, limiter=limiter or RateLimiter())
    app.add_middleware(CORSMiddleware, allow_origins=["https://ashborne-volt.vercel.app"],
                       allow_origin_regex=VERCEL_PREVIEW_ORIGIN, allow_credentials=False,
                       allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Content-Type"])
    return TestClient(app)


def test_legacy_routes_are_not_reachable():
    c = _client()
    assert c.post("/scrape/run-now").status_code == 404
    assert c.get("/docs").status_code == 404
    assert c.delete("/account/data").status_code == 404
    assert c.get("/health").status_code == 200


def test_allowlist_is_method_aware():
    assert is_public("GET", "/health")
    assert not is_public("DELETE", "/health")
    assert is_public("POST", "/resume/parse")
    assert not is_public("GET", "/resume/parse")
    assert is_public("OPTIONS", "/anything")   # preflight is answered by CORS


def test_cors_only_trusts_this_project():
    c = _client()
    ok = c.get("/health", headers={"Origin": "https://ashborne-volt-git-main-kumar.vercel.app"})
    assert ok.headers.get("access-control-allow-origin") == "https://ashborne-volt-git-main-kumar.vercel.app"
    evil = c.get("/health", headers={"Origin": "https://evil-site.vercel.app"})
    assert "access-control-allow-origin" not in evil.headers
    assert "access-control-allow-credentials" not in ok.headers


def test_generate_is_rate_limited():
    c = _client()
    codes = [c.post("/resume-studio/tailor/generate").status_code for _ in range(13)]
    assert codes[:12] == [200] * 12
    assert codes[12] == 429


def test_rate_limit_window_slides():
    rl = RateLimiter()
    for i in range(12):
        assert rl.allow("1.2.3.4", "/resume-studio/tailor/generate", now=1000.0 + i)[0]
    assert not rl.allow("1.2.3.4", "/resume-studio/tailor/generate", now=1100.0)[0]
    assert rl.allow("1.2.3.4", "/resume-studio/tailor/generate", now=1000.0 + 3601)[0]
    assert rl.allow("5.6.7.8", "/resume-studio/tailor/generate", now=1100.0)[0]


def test_oversized_body_rejected_before_reading():
    c = _client()
    r = c.post("/resume-studio/tailor/generate", content=b"x",
               headers={"content-length": str(50 * 1024 * 1024)})
    assert r.status_code == 413


def test_security_headers_present():
    r = _client().get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"


def test_real_app_registers_every_public_route():
    """Each allowlisted route must exist in main.py, or the frontend calls a 404."""
    from backend.app.main import app
    from backend.app.security import PUBLIC_ROUTES

    paths = {(m, r.path) for r in app.routes for m in getattr(r, "methods", set())}
    for method, rx in PUBLIC_ROUTES:
        assert any(m == method and rx.match(p) for m, p in paths), (method, rx.pattern)
