import re
import logging
from app.generators.openrouter_client import OpenRouterClient
from app.generators.utils import load_prompt


def _clean_text(text: str) -> str:
    """Убирает markdown и AI-артефакты."""
    text = re.sub(r"#{1,6}\s+\*{0,2}(.+?)\*{0,2}", r"\1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text)
    text = re.sub(r"\(Продол.+?\)", "", text, flags=re.DOTALL)
    text = re.sub(r"\(продол.+?\)", "", text, flags=re.DOTALL)
    text = re.sub(r"\(Текст.+?\)", "", text, flags=re.DOTALL)
    text = re.sub(r"^\s*-\s+\*\*(.+?)\*\*", r"\1", text, flags=re.MULTILINE)
    text = text.replace("—", "-").replace("–", "-")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# Слова/фразы-маркеры, по которым чистим "второй финал" и метаразметку модели
_BANNED_TAILS = (
    "недавно я заметил",
    "недавно я заметила",
    "недавно я понял",
    "недавно я поняла",
    "а ещё я замечаю",
    "а ещё я замечаю,",
    "хочу ещё добавить",
    "мне вспомнилась ещё одна",
    "продолжение следует",
)


def _cut_second_ending(text: str) -> str:
    """
    Если модель после финала начала новую историю с ключевых фраз —
    отрезаем всё после этого маркера.
    """
    lower = text.lower()
    earliest = -1
    for marker in _BANNED_TAILS:
        idx = lower.find(marker)
        if idx != -1 and (earliest == -1 or idx < earliest):
            earliest = idx
    if earliest == -1:
        return text
    return text[:earliest].rstrip()


def generate_article(
    settings,
    *,
    topic: str,
    title: str,
    plan: str,
    hero: str,
    emotion: str,
    format: str,
) -> str:
    logger = logging.getLogger(__name__)

    prompt_text = load_prompt(settings, "article_prompt.txt")
    user_prompt = prompt_text.format(
        topic=topic,
        title=title,
        plan=plan,
        hero=hero,
        emotion=emotion,
        format=format,
    )

    client = OpenRouterClient(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        model=settings.openrouter_model,
        timeout_s=settings.openrouter_timeout_s,
        logger=logger,
    )

    system = (
        "Ты пишешь для Дзена на русском. "
        "Только живой текст, никакого markdown, никаких заголовков разделов, "
        "никаких комментариев о тексте. "
        "Соблюдай квоты на конкретику (цифры, реплики, бренды) из промта. "
        "Финал ровно один. После финала ничего не пиши."
    )

    text = client.chat(
        system=system,
        user=user_prompt,
        temperature=0.85,
        max_tokens=2600,
    )
    text = _clean_text(text)
    text = _cut_second_ending(text)

    logger.info(f"Generated article: {len(text)} chars, title: {title[:50]}")
    return text.strip()
