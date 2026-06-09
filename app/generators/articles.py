import logging
from app.generators.openrouter_client import OpenRouterClient
from app.generators.utils import load_prompt


def generate_article(settings, *, topic: str, title: str) -> str:
    logger = logging.getLogger(__name__)

    prompt_text = load_prompt(settings, "article_prompt.txt")
    user_prompt = prompt_text.format(topic=topic, title=title)

    client = OpenRouterClient(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        model=settings.openrouter_model,
        timeout_s=settings.openrouter_timeout_s,
        logger=logger,
    )

    # Первый запрос
    text = client.chat(
        system="Ты пишешь для Дзена на русском.",
        user=user_prompt,
        temperature=0.85,
        max_tokens=2200,
    )

    # Если статья короткая — запросить продолжение
    if len(text) < 3500:
        logger.info(f"Article too short ({len(text)} chars), requesting continuation")
        continuation_prompt = (
            f"Текст получился коротким (около {len(text)} символов). "
            f"Продолжи эту же статью в том же стиле, добавь бытовых деталей и разбор, "
            f"чтобы суммарно было 4500–6500 символов. "
            f"Не повторяйся. Верни только продолжение текста."
        )
        continuation = client.chat(
            system="Ты пишешь для Дзена на русском.",
            user=continuation_prompt,
            temperature=0.85,
            max_tokens=1500,
        )
        text = text + "\n\n" + continuation

    logger.info(f"Generated article: {len(text)} chars, title: {title[:50]}")
    return text.strip()