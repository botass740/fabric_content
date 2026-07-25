import logging
from app.generators.openrouter_client import OpenRouterClient
from app.generators.anthropic_client import AnthropicClient


def get_llm_client(settings, logger: logging.Logger | None = None):
    """Возвращает LLM-клиент по настройке LLM_PROVIDER: anthropic | openrouter."""
    if settings.llm_provider == "anthropic":
        return AnthropicClient(
            auth_token=settings.anthropic_auth_token,
            base_url=settings.anthropic_base_url,
            model=settings.anthropic_model,
            timeout_s=settings.anthropic_timeout_s,
            logger=logger,
        )
    return OpenRouterClient(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        model=settings.openrouter_model,
        timeout_s=settings.openrouter_timeout_s,
        reasoning_effort=settings.openrouter_reasoning_effort,
        logger=logger,
    )
