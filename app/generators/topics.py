import logging
from app.generators.knowledge_helper import get_knowledge_base
from app.generators.llm import get_llm_client
from app.generators.utils import load_prompt, parse_json_list
from app.generators.topic_matrix import format_recent_topics


def _build_knowledge_context(logger: logging.Logger) -> str:
    """Собирает блок контекста из базы знаний для промпта тем.

    Возвращает пустую строку, если база знаний недоступна — тогда генерация
    работает как раньше (обратная совместимость).
    """
    try:
        kb = get_knowledge_base()
        if not kb.is_loaded():
            logger.info("Knowledge base not loaded — topics without KB context")
            return ""

        clusters = kb.get_all_clusters()
        overlap = kb._data.get("topic_clusters", {}).get("overlap_analysis", {})
        combinations = overlap.get("most_common_combinations", [])

        if not clusters and not combinations:
            logger.info("Knowledge base empty — topics without KB context")
            return ""

        # Топ-6 кластеров по доле статей
        clusters_text = "УСПЕШНЫЕ ТЕМАТИЧЕСКИЕ НАПРАВЛЕНИЯ:\n\n"
        top_clusters = sorted(
            clusters.items(),
            key=lambda item: item[1].get("percentage") or 0,
            reverse=True,
        )[:6]
        for name, data in top_clusters:
            pct = data.get("percentage") or 0
            words = [
                w["word"] for w in data.get("top_words", [])[:5]
                if isinstance(w, dict) and "word" in w
            ]
            examples = data.get("example_titles") or []
            clusters_text += f"- {name} ({pct:.1f}% статей): {', '.join(words)}\n"
            if examples:
                clusters_text += f"  Пример: {examples[0]}\n"

        combo_text = "РАБОТАЮЩИЕ КОМБИНАЦИИ ТЕМ:\n"
        for combo in combinations[:3]:
            clusters_str = " + ".join(combo.get("clusters", []))
            combo_text += f"- {clusters_str} ({combo.get('count', 0)} статей)\n"

        logger.info(
            "Knowledge base applied to topics: %d clusters, %d combinations",
            len(clusters),
            len(combinations),
        )

        return (
            "ДАЙДЖЕСТ ИЗ БАЗЫ ЗНАНИЙ (эти тематические направления и их комбинации "
            "реально работают в финансовых каналах Дзена).\n"
            "Используй их как ориентир, но формулируй под заданную комбинацию осей.\n\n"
            f"{clusters_text}\n{combo_text}\n"
            "ОРИГИНАЛЬНЫЕ ИНСТРУКЦИИ:\n"
        )
    except Exception as e:
        logger.warning("Knowledge base enrichment failed, falling back to default prompt: %s", e)
        return ""


def _normalize_topic(text: str) -> str:
    """
    Очистить тему от служебных меток, которые иногда добавляет LLM
    («Заголовок: …», «1. История: …»), и вернуть чистую тему.
    """
    import re

    text = text.strip()
    # Убрать нумерацию в начале: "1.", "2)", "3."
    text = re.sub(r"^\d+[\.\)]\s*", "", text)

    # Убрать известные метки (регистронезависимо), повторно, пока есть что убирать
    prefixes = [
        r"^заголовок\s*:\s*",
        r"^история\s*:\s*",
        r"^тема\s*:\s*",
        r"^topic\s*:\s*",
        r"^title\s*:\s*",
        r"^сюжет\s*:\s*",
        r"^описание\s*:\s*",
    ]
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            new_text = re.sub(prefix, "", text, flags=re.IGNORECASE)
            if new_text != text:
                text = new_text
                changed = True
    return text.strip()


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
    prompt_text = prompt_text.format(
        n=n,
        hero=combination["hero"],
        emotion=combination["emotion"],
        format=combination["format"],
        trigger=combination["trigger"],
        hook_type=combination["hook_type"],
        recent_topics=format_recent_topics(recent_topics or []),
        live_triggers=live_triggers,
    )

    kb_context = _build_knowledge_context(logger)
    user_prompt = kb_context + prompt_text if kb_context else prompt_text

    client = get_llm_client(settings, logger)

    response = client.chat(
        system="Ты пишешь для Дзена на русском.",
        user=user_prompt,
        temperature=0.95,
        max_tokens=4096,
    )

    topics = parse_json_list(response)
    topics = [_normalize_topic(t) for t in topics if t.strip()]
    topics = [t[:120] for t in topics if t and len(t) > 10]
    topics = list(dict.fromkeys(topics))

    logger.info(f"Generated {len(topics)} topics for combination {combination['hero']} / {combination['trigger']}")
    return topics[:n]


if __name__ == "__main__":
    tests = [
        ("Заголовок: Галя взяла лишнее", "Галя взяла лишнее"),
        ("1. История: Дед хранил миллион", "Дед хранил миллион"),
        ("Тема: Ключевая ставка: итоги", "Ключевая ставка: итоги"),
        ("Акция 1+1 сорвала план", "Акция 1+1 сорвала план"),
        ("  3) Сюжет: Мать копила 30 лет  ", "Мать копила 30 лет"),
    ]
    print("Тест _normalize_topic:")
    all_ok = True
    for input_text, expected in tests:
        result = _normalize_topic(input_text)
        status = "✅" if result == expected else "❌"
        if result != expected:
            all_ok = False
        print(f"  {status} '{input_text}' → '{result}'")
        if result != expected:
            print(f"       Ожидалось: '{expected}'")
    print(f"\n{'✅ Все тесты прошли' if all_ok else '❌ Есть ошибки'}")
