"""Outbound notifications. Critical alerts are pushed to an optional webhook
(Teams / Slack / any HTTP endpoint) set in NOTIFY_WEBHOOK_URL. In-app alerts are always stored."""
import logging

import httpx

from app.config import settings

log = logging.getLogger("solarclear.notify")


def send_webhook(title: str, lines: list[str]) -> bool:
    url = settings.notify_webhook_url
    if not url or not lines:
        return False
    text = f"**{title}**\n" + "\n".join(f"- {line}" for line in lines[:20])
    try:
        httpx.post(url, json={"text": text}, timeout=5).raise_for_status()
        return True
    except httpx.HTTPError as exc:
        log.warning("Webhook notification failed: %s", exc)
        return False
