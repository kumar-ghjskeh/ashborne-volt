"""Web Push (VAPID) delivery for saved-search alerts — free, no third party.

Sending requires the VAPID *private* key (settings.vapid_private_key). If it isn't
set, sending is a no-op so the app runs fine without alerts configured.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from sqlmodel import Session, select

from ..config import settings
from ..models import PushSubscription

logger = logging.getLogger(__name__)

PushResult = Literal["ok", "expired", "error", "disabled"]


def send_web_push(sub: PushSubscription, payload: dict) -> PushResult:
    """Send one push. Returns 'expired' for dead subscriptions (404/410) so the
    caller can prune them, 'ok' on success, 'error'/'disabled' otherwise."""
    if not settings.vapid_private_key:
        return "disabled"
    try:
        from pywebpush import webpush, WebPushException
    except Exception:
        logger.warning("pywebpush not installed — cannot send web push")
        return "disabled"
    try:
        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
            ttl=86400,
        )
        return "ok"
    except WebPushException as e:  # type: ignore[misc]
        code = getattr(getattr(e, "response", None), "status_code", None)
        if code in (404, 410):
            return "expired"
        logger.info("web push failed (%s): %s", code, e)
        return "error"
    except Exception as e:
        logger.info("web push error: %s", e)
        return "error"


def notify_all(session: Session, *, title: str, body: str, url: str = "/", tag: str | None = None) -> int:
    """Push a notification to every subscribed device; prune dead subscriptions.
    Returns the number successfully delivered."""
    subs = session.exec(select(PushSubscription)).all()
    if not subs:
        return 0
    payload = {"title": title, "body": body, "url": url}
    if tag:
        payload["tag"] = tag
    sent = 0
    pruned = 0
    for s in subs:
        result = send_web_push(s, payload)
        if result == "ok":
            sent += 1
        elif result == "expired":
            session.delete(s)
            pruned += 1
    if pruned:
        session.commit()
    return sent
