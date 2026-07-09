import logging
from app.generators.openrouter_client import OpenRouterClient
from app.generators.utils import load_prompt, parse_json_list
from app.generators.topic_matrix import format_recent_topics


def generate_topics(
    settings,
    *,
    combination: dict,
    live_triggers: str,
    recent_topics: list[str] | None = None,
    n: int = 3,
) -> list[str]:
    """
    Генерирует темы в рамках заданной комбинации осей.
    combination: dict с ключами hero, emotion, format, trigger, hook_type
    live_triggers: готовый форматированный блок актуальных триггеров (см. app.context.trends.load_trend_context)
    recent_topics: список ранее использованных тем для передачи в промт
    """
    logger = logging.getLogger(__name__)

    prompt_text = load_prompt(settings, "topic_prompt.txt")
    user_prompt = prompt_text.format(
        n=n,
        hero=combination["hero"],
        emotion=combination["emotion"],
        format=combination["format"],
        trigger=combination["trigger"],
        hook_type=combination["hook_type"],
        recent_topics=format_recent_topics(recent_topics or []),
        live_triggers=live_triggers,
    )

    client = OpenRouterClient(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        model=settings.openrouter_model,
        timeout_s=settings.openrouter_timeout_s,
        logger=logger,
    )

    response = client.chat(
        system="Ты пишешь для Дзена на русском.",
        user=user_prompt,
        temperature=0.95,
        max_tokens=600,
    )

    topics = parse_json_list(response)
    topics = [t.strip()[:120] for t in topics if t.strip()]
    topics = list(dict.fromkeys(topics))

    logger.info(f"Generated {len(topics)} topics for combination {combination['hero']} / {combination['trigger']}")
    return topics[:n]
