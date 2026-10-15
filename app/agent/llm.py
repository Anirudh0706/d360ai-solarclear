"""Azure OpenAI client (same env vars as the team's other projects).

Token economy: reasoning_effort=low, a hard max_completion_tokens cap, and the
caller keeps prompts small. If the deployment or API version rejects
reasoning_effort we retry once without it and remember that.
"""
import logging

from app.config import settings

log = logging.getLogger("solarclear.llm")
_effort_supported = True


def get_client():
    if not settings.llm_enabled:
        return None
    from openai import AzureOpenAI

    return AzureOpenAI(
        api_key=settings.azure_api_key,
        azure_endpoint=settings.azure_endpoint,
        api_version=settings.azure_api_version,
        max_retries=2,
        timeout=90,
    )


def complete(client, messages: list[dict], tools: list[dict] | None = None, max_tokens: int | None = None):
    """One chat completion. GPT-5-class deployments take max_completion_tokens and no temperature."""
    global _effort_supported
    from openai import BadRequestError

    kwargs = {
        "model": settings.azure_deployment,
        "messages": messages,
        "max_completion_tokens": max_tokens or settings.agent_max_tokens,
    }
    if tools:
        kwargs["tools"] = tools
    if _effort_supported and settings.agent_reasoning_effort:
        kwargs["reasoning_effort"] = settings.agent_reasoning_effort
    try:
        return client.chat.completions.create(**kwargs)
    except BadRequestError as exc:
        if "reasoning_effort" in kwargs and "reasoning" in str(exc).lower():
            log.info("Deployment rejected reasoning_effort; retrying without it")
            _effort_supported = False
            kwargs.pop("reasoning_effort")
            return client.chat.completions.create(**kwargs)
        raise


def usage_of(response) -> tuple[int, int]:
    usage = getattr(response, "usage", None)
    return (usage.prompt_tokens, usage.completion_tokens) if usage else (0, 0)
