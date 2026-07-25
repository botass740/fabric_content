import logging
from app.generators.llm import get_llm_client
from app.generators.utils import load_prompt, parse_json_list


def generate_titles(
    settings,
    *,
    topic: str,
    hook_type: str,
    hero: str,
    n: int = 8,
) -> list[str]:
    logger = logging.getLogger(__name__)

    prompt_text = load_prompt(settings, "title_prompt.txt")
    user_prompt = prompt_text.format(
        topic=topic,
        hook_type=hook_type,
        hero=hero,
        n=n,
    )

    client = get_llm_client(settings, logger)

    response = client.chat(
        system="Ты пишешь для Дзена на русском.",
        user=user_prompt,
        temperature=0.9,
        max_tokens=2000,
    )

    titles = parse_json_list(response)
    titles = [t.strip()[:120] for t in titles if t.strip()]
    titles = list(dict.fromkeys(titles))

    logger.info(f"Generated {len(titles)} titles for topic: {topic[:50]}")
    return titles[:n]
