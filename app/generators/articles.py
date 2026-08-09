import re
import logging
from app.generators.knowledge_helper import get_knowledge_base
from app.generators.llm import get_llm_client
from app.generators.utils import load_prompt


def _build_knowledge_context(logger: logging.Logger) -> str:
    """Собирает блок контекста из базы знаний для промпта статьи.

    Добавляет ориентиры по объёму/структуре из корпуса и реальные примеры
    сильных хуков. Возвращает пустую строку, если база знаний недоступна —
    тогда генерация работает как раньше (обратная совместимость).
    """
    try:
        kb = get_knowledge_base()
        if not kb.is_loaded():
            logger.info("Knowledge base not loaded — article without KB context")
            return ""

        structure = kb._data.get("article_structure", {})
        length_info = structure.get("recommended_length", {})
        rec_struct = structure.get("recommended_structure", {})
        hook_types = kb._data.get("hooks", {}).get("hook_types", {})

        optimal_words = length_info.get("optimal_words")
        paragraphs = rec_struct.get("paragraphs_optimal")
        headers = rec_struct.get("headers_count_optimal")

        structure_text = "СТРУКТУРА (ориентиры по реальным статьям корпуса):\n"
        if optimal_words:
            structure_text += f"- Оптимальный объём: ~{optimal_words} слов\n"
        if paragraphs:
            structure_text += f"- Абзацев: ~{paragraphs}\n"
        if headers:
            structure_text += (
                f"- Подзаголовков: до {headers} (как отдельные строки-абзацы, "
                f"без markdown-разметки ##)\n"
            )
        structure_text += "- Драматургия: вступление-хук → основная часть → финал на действии\n"

        # Реальные типы хуков с рабочим примером (пропускаем обобщённый тип "other"
        # и типы без примеров; длинные новостные сводки не берём)
        hooks_text = "СИЛЬНЫЕ ХУКИ (типы и примеры из корпуса 560 статей):\n"
        picked = 0
        for htype, hdata in hook_types.items():
            if htype == "other":
                continue
            examples = [
                e for e in hdata.get("examples", [])
                if isinstance(e, str) and e.strip() and len(e) < 160
            ]
            if not examples:
                continue
            template = hdata.get("template", "?")
            ex = re.sub(r"\s+", " ", examples[0]).strip()[:120]
            hooks_text += f"- {htype} (шаблон: «{template}»): {ex}\n"
            picked += 1
            if picked >= 3:
                break

        logger.info(
            "Knowledge base applied to article prompt: "
            "%d hook types, words=%s, paragraphs=%s",
            picked,
            optimal_words,
            paragraphs,
        )

        return (
            "ДАЙДЖЕСТ ИЗ БАЗЫ ЗНАНИЙ (на основе анализа 560 финансовых статей Дзена).\n"
            "Используй для выбора хук-открытия и объёма, но фразы и детали бери из плана "
            "и актуального фона.\n\n"
            f"{structure_text}\n{hooks_text}\n"
            "ОРИГИНАЛЬНЫЕ ИНСТРУКЦИИ:\n"
        )
    except Exception as e:
        logger.warning("Knowledge base enrichment failed, falling back to default prompt: %s", e)
        return ""


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

# Регэкспы афористических финалов — паттерны, которые модель постоянно пробивает.
# Внимание: в _clean_text длинные тире (— и –) заменяются на обычный дефис (-),
# поэтому паттерны используют класс [-—–] для устойчивости.
_DASH = r"[-—–]"
_APHORISM_PATTERNS = (
    rf"иногда\s+[^\.\n]{{2,60}}\s+{_DASH}\s+значит\s+[^\.\n]{{2,60}}",
    rf"настоящ(ая|ий|ее)\s+[а-яё]+\s+{_DASH}\s+это\s+не\s+[^\.\n]+",
    rf"главное\s+{_DASH}\s+не\s+[^,\.\n]+,\s+а\s+[^\.\n]+",
    rf"[а-яё]+\s+{_DASH}\s+это\s+не\s+про\s+[а-яё]+,\s+это\s+про\s+[а-яё]+",
    r"и,?\s+кажется,?\s+это\s+того\s+стоит",
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


def _detect_aphorism_ending(text: str, logger: logging.Logger) -> None:
    """
    Проверяет последний абзац на афористический паттерн.
    Ничего не режет (риск испортить нормальный текст), только пишет warning в лог.
    """
    tail = text[-500:].lower()
    for pattern in _APHORISM_PATTERNS:
        m = re.search(pattern, tail)
        if m:
            logger.warning(
                f"Aphoristic ending detected: '{m.group(0)[:100]}...'. "
                f"Финал пробил запрет — рекомендуется регенерация."
            )
            return


def generate_article(
    settings,
    *,
    topic: str,
    title: str,
    plan: str,
    hero: str,
    emotion: str,
    format: str,
    live_triggers: str,
) -> str:
    logger = logging.getLogger(__name__)

    prompt_text = load_prompt(settings, "article_prompt.txt")
    prompt_text = prompt_text.format(
        topic=topic,
        title=title,
        plan=plan,
        hero=hero,
        emotion=emotion,
        format=format,
        live_triggers=live_triggers,
    )

    kb_context = _build_knowledge_context(logger)
    user_prompt = kb_context + prompt_text if kb_context else prompt_text

    client = get_llm_client(settings, logger)

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
        max_tokens=8000,
    )
    text = _clean_text(text)
    text = _cut_second_ending(text)

    length = len(text)
    logger.info(f"Generated article: {length} chars, title: {title[:50]}")
    if length < 2800:
        logger.warning(
            f"Article too short ({length} chars, target 3200-4500). "
            f"Дзен-алгоритм плохо продвигает короткие статьи. "
            f"Рекомендуется регенерация (кнопка 🔄 в боте)."
        )
    _detect_aphorism_ending(text, logger)
    return text.strip()
