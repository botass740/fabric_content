import logging
from app.generators.openrouter_client import OpenRouterClient
from app.generators.utils import load_prompt, parse_json_list


def generate_titles(settings, *, topic: str, n: int = 8) -> list[str]:
    logger = logging.getLogger(__name__)

    prompt_text = load_prompt(settings, "title_prompt.txt")
    user_prompt = prompt_text.format(topic=topic, n=n)

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
        temperature=0.9,
        max_tokens=600,
    )

    titles = parse_json_list(response)
    titles = [t.strip()[:120] for t in titles if t.strip()]
    titles = list(dict.fromkeys(titles))

    logger.info(f"Generated {len(titles)} titles for topic: {topic[:50]}")
    return titles[:n]