import json
import logging
from app.generators.llm import get_llm_client
from app.generators.utils import load_prompt, extract_json


def generate_article_plan(
    settings,
    *,
    topic: str,
    title: str,
    hero: str,
    emotion: str,
    format: str,
    live_triggers: str,
    feedback: str | None = None,
) -> tuple[str, dict]:
    """
    Генерирует структурированный план статьи.

    Возвращает кортеж (plan_text, plan_json):
      - plan_text: читаемая текстовая версия плана для передачи в article_prompt.
      - plan_json: сырой JSON-словарь плана для story_check.

    Если передан feedback (JSON-строка с замечаниями story_check),
    он добавляется в конец промпта для регенерации.

    live_triggers: готовый форматированный блок актуальных триггеров.
    Тот же самый, что передавался в generate_topics — иначе тема и план разъедутся.
    """
    logger = logging.getLogger(__name__)

    prompt_text = load_prompt(settings, "article_plan_prompt.txt")
    user_prompt = prompt_text.format(
        topic=topic,
        title=title,
        hero=hero,
        emotion=emotion,
        format=format,
        live_triggers=live_triggers,
    )

    if feedback:
        user_prompt += f"""

ПРЕДЫДУЩИЙ ПЛАН НЕ ПРОШЁЛ STORY CHECK.

Ошибки редактора:

{feedback}

Создай новый план.
Не исправляй предыдущий план косметически.
Перестрой сцены, конфликт или turning point, если этого требуют ошибки.
Устрани причины каждой critical issue.
Не добавляй новые детали и персонажей только для маскировки проблемы.
"""

    client = get_llm_client(settings, logger)

    system = "Ты редактор Яндекс Дзена. Возвращай только JSON без пояснений и markdown."

    max_retries = 3
    plan_json = None
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat(
                system=system,
                user=user_prompt,
                temperature=0.75,
                max_tokens=6000,
            )
        except Exception as e:
            last_error = f"API error: {e}"
            logger.error(f"[ARTICLE_PLAN] Technical attempt {attempt}/{max_retries} failed: {last_error}")
            if attempt < max_retries:
                continue
            break

        if not response or not response.strip():
            last_error = "empty response"
            logger.error(f"[ARTICLE_PLAN] Technical attempt {attempt}/{max_retries} failed: {last_error}")
            if attempt < max_retries:
                continue
            break

        plan_json = extract_json(response, logger=logger)
        if plan_json is not None:
            break

        last_error = "JSON parse failure"
        logger.error(f"[ARTICLE_PLAN] Technical attempt {attempt}/{max_retries} failed: {last_error}")
        if attempt < max_retries:
            continue
        break

    if plan_json is None:
        logger.error(f"[ARTICLE_PLAN] All {max_retries} technical attempts exhausted. Last error: {last_error}")
        raise ValueError("Не удалось извлечь JSON из ответа LLM при генерации плана статьи")

    # Диагностика: логируем сам план и предупреждаем о пропущенных полях
    logger.info(f"Plan JSON keys: {sorted(plan_json.keys())}")
    logger.info(f"Plan JSON full: {json.dumps(plan_json, ensure_ascii=False)[:2000]}")

    missing = []
    for required in (
        "core_conflict", "core_insight", "emotion_arc", "narrator_stance",
        "reader_question", "opening_scene", "scenes", "turning_point",
        "details", "ending_goal", "final_image",
    ):
        val = plan_json.get(required)
        if not val or (isinstance(val, list) and not val):
            missing.append(required)
    if missing:
        logger.warning(f"Plan missing/empty fields: {missing}. Статья потеряет часть структуры.")

    # Форматируем сцены
    scenes_text = ""
    for i, s in enumerate(plan_json.get("scenes", []), 1):
        scene = s.get("scene", "") if isinstance(s, dict) else str(s)
        purpose = (
            f" (цель: {s.get('scene_purpose', '')})"
            if isinstance(s, dict) and s.get("scene_purpose")
            else ""
        )
        scenes_text += f"  Сцена {i}: {scene}{purpose}\n"
    scenes_text = scenes_text.strip()

    # Форматируем turning point
    tp = plan_json.get("turning_point", {})
    if isinstance(tp, dict):
        tp_text = (
            f"Тип: {tp.get('turning_point_type', '')}\n"
            f"Что меняется: {tp.get('change', '')}\n"
            f"Через что: {tp.get('trigger', '')}"
        ).strip()
    else:
        tp_text = str(tp)

    plan_text = f"""
Центральный конфликт:
{plan_json.get('core_conflict', '')}

Главный инсайт:
{plan_json.get('core_insight', '')}

Эмоциональная арка:
{' → '.join(plan_json.get('emotion_arc', []))}

Позиция рассказчика (обязательно транслируй в тексте — воспоминаниями, реакциями, скрытой раной):
{plan_json.get('narrator_stance', '')}

Вопрос читателя (удерживай, не отвечай раньше времени):
{plan_json.get('reader_question', '')}

Открывающая сцена (начни внутри неё):
{plan_json.get('opening_scene', '')}

Сцены (каждая меняет ситуацию, ставку или понимание):
{scenes_text}

Поворотный момент (turning point):
{tp_text}

Бытовые детали:
{chr(10).join('- ' + d for d in plan_json.get('details', []))}

Финал:
{plan_json.get('ending_goal', '')}

Финальный образ (после него — стоп):
{plan_json.get('final_image', '')}
""".strip()

    logger.info(f"Generated article plan for: {title[:50]}")
    return plan_text, plan_json