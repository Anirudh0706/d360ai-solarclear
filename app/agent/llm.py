"""D360 AI engine client: one HTTPS call per completion, no vendor SDK.

The engine speaks the standard chat-completions JSON format (messages, tools, tool_calls,
usage). Responses are turned into attribute-style objects so the agent code reads
`response.choices[0].message.tool_calls`.

Token economy: reasoning_effort=low and a hard max_completion_tokens cap on every call.
If the engine rejects reasoning_effort we retry once without it and remember that.
"""
import logging
import time
from types import SimpleNamespace

import httpx

from app.config import settings

log = logging.getLogger("solarclear.llm")
_effort_supported = True
RETRY_STATUS = {429, 500, 502, 503, 504}


class EngineError(Exception):
    """The D360 AI engine returned an error or could not be reached."""


class D360Client:
    def __init__(self, endpoint: str, api_key: str, timeout: float = 90, retries: int = 2):
        self.endpoint, self.api_key, self.timeout, self.retries = endpoint, api_key, timeout, retries

    def post(self, payload: dict) -> httpx.Response:
        headers = {"api-key": self.api_key, "Content-Type": "application/json"}
        for attempt in range(self.retries + 1):
            try:
                resp = httpx.post(self.endpoint, headers=headers, json=payload, timeout=self.timeout)
            except httpx.HTTPError as exc:
                if attempt == self.retries:
                    raise EngineError(f"D360 AI engine unreachable: {type(exc).__name__}") from exc
            else:
                if resp.status_code not in RETRY_STATUS or attempt == self.retries:
                    return resp
            time.sleep(1.5 * (attempt + 1))  # back off before retrying
        raise EngineError("D360 AI engine unreachable")


def get_client() -> D360Client | None:
    if not settings.llm_enabled:
        return None
    return D360Client(settings.d360_endpoint, settings.d360_api_key)


def _to_namespace(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{k: _to_namespace(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_to_namespace(v) for v in value]
    return value


def complete(client: D360Client, messages: list[dict], tools: list[dict] | None = None, max_tokens: int | None = None):
    """One chat completion. Reasoning-class engines take max_completion_tokens and no temperature."""
    global _effort_supported
    payload = {"messages": messages, "max_completion_tokens": max_tokens or settings.agent_max_tokens}
    if tools:
        payload["tools"] = tools
    if _effort_supported and settings.agent_reasoning_effort:
        payload["reasoning_effort"] = settings.agent_reasoning_effort

    resp = client.post(payload)
    if resp.status_code == 400 and "reasoning_effort" in payload and "reasoning" in resp.text.lower():
        log.info("Engine rejected reasoning_effort; retrying without it")
        _effort_supported = False
        payload.pop("reasoning_effort")
        resp = client.post(payload)
    if resp.status_code >= 400:
        log.warning("D360 AI engine error %s: %s", resp.status_code, resp.text[:300])
        raise EngineError(f"D360 AI engine returned HTTP {resp.status_code}")

    data = resp.json()
    for choice in data.get("choices", []):  # make sure the attributes the agent reads always exist
        choice.setdefault("message", {}).setdefault("tool_calls", None)
        choice["message"].setdefault("content", None)
    return _to_namespace(data)


def usage_of(response) -> tuple[int, int]:
    usage = getattr(response, "usage", None)
    return (getattr(usage, "prompt_tokens", 0), getattr(usage, "completion_tokens", 0)) if usage else (0, 0)
