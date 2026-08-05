import logging
from app.generators.knowledge_helper import get_knowledge_base
from app.generators.llm import get_llm_client
from app.generators.utils import load_prompt, parse_json_list


def _build_knowledge_context(logger: logging.Logger) -> str:
    """Собирает блок контекста из базы знаний для промпта заголовков.

    Возвращает пустую строку, если база знаний недоступна — тогда генерация
    работает как раньше (обратная совместимость).
    """
    try:
        kb = get_knowledge_base()
        if not kb.is_loaded():
            logger.info("Knowledge base not loaded — title generation without KB context")
            return ""

        patterns = kb.get_title_patterns()
        power_words = kb.get_power_words_titles(limit=20)
        bigrams = kb.get_power_bigrams(limit=10)

        if not patterns and not power_words and not bigrams:
            logger.info("Knowledge base empty — title generation without KB context")
            return ""

        # Топ-5 паттернов по частоте встречаемости
        patterns_text = "ПРОВЕРЕННЫЕ ПАТТЕРНЫ ЗАГОЛОВКОВ (из анализа 560 статей):\n\n"
        for p in patterns[:5]:
            if not isinstance(p, dict):
                continue
            freq = p.get("frequency", 0) or 0
            name = p.get("name", "?")
            patterns_text += f"- {name} ({freq * 100:.0f}%): шаблон «{p.get('template', '')}»\n"
            examples = p.get("examples", [])
            if examples:
                patterns_text += f"  Примеры: {'; '.join(str(e) for e in examples[:2])}\n"
            if p.get("tips"):
                patterns_text += f"  Совет: {p['tips']}\n"

        words_text = f"СИЛЬНЫЕ СЛОВА ДЛЯ ЗАГОЛОВКОВ: {', '.join(power_words[:15])}\n"
        bigrams_text = f"РАБОТАЮЩИЕ ФРАЗЫ: {', '.join(bigrams[:8])}"

        logger.info(
            "Knowledge base applied to title prompt: %d patterns, %d words, %d bigrams",
            len(patterns[:5]),
            len(power_words),
            len(bigrams),
        )

        return (
            "ДАЙДЖЕСТ ИЗ БАЗЫ ЗНАНИЙ (эти паттерны реально работают в финансовых каналах Дзена).\n"
            "Используй их как источник шаблонов и лексики, но формулируй под заданную тему.\n\n"
            f"{patterns_text}\n{words_text}\n{bigrams_text}\n\n"
            "ОРИГИНАЛЬНЫЕ ИНСТРУКЦИИ:\n"
        )
    except Exception as e:
        logger.warning("Knowledge base enrichment failed, falling back to default prompt: %s", e)
        return ""


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
    prompt_text = prompt_text.format(
        topic=topic,
        hook_type=hook_type,
        hero=hero,
        n=n,
    )

    kb_context = _build_knowledge_context(logger)
    user_prompt = kb_context + prompt_text if kb_context else prompt_text

    client = get_llm_client(settings, logger)

    response = client.chat(
        system="Ты пишешь для Дзена на русском.",
        user=user_prompt,
        temperature=0.9,
        max_tokens=8192,
    )

    titles = parse_json_list(response)
    titles = [t.strip()[:120] for t in titles if t.strip()]
    titles = list(dict.fromkeys(titles))

    logger.info(f"Generated {len(titles)} titles for topic: {topic[:50]}")
    return titles[:n]
