import json
import logging
from app.generators.llm import get_llm_client
from app.generators.utils import load_prompt, extract_json


def _validate_story_check(check: dict, logger: logging.Logger) -> str | None:
    """Валидирует JSON-ответ story_check. Возвращает None или строку с описанием ошибки."""
    if not isinstance(check, dict):
        return "JSON root is not object"

    if "status" not in check:
        return "Missing required field: status"

    if "score" not in check:
        return "Missing required field: score"

    status = check.get("status")
    if not isinstance(status, str):
        return f"status is not a string: {type(status).__name__}"

    status_upper = status.strip().upper()
    check["status"] = status_upper
    if status_upper not in ("PASS", "FAIL"):
        return f"status is not PASS or FAIL: {status_upper}"

    score = check.get("score")
    try:
        score_int = int(score)
    except (ValueError, TypeError):
        return f"score cannot be converted to int: {score!r}"

    if score_int < 1 or score_int > 10:
        return f"score out of range 1-10: {score_int}"

    check["score"] = score_int

    issues = check.get("issues")
    if issues is not None:
        if not isinstance(issues, list):
            return f"issues is not a list: {type(issues).__name__}"
        for i, issue in enumerate(issues):
            if not isinstance(issue, dict):
                return f"issues[{i}] is not an object: {type(issue).__name__}"

    return None


def generate_story_check(
    settings,
    *,
    topic: str,
    title: str,
    plan_json: dict,
    max_technical_attempts: int = 3,
) -> dict | None:
    """
    Проверяет план статьи через story_check_prompt.

    Внутренний retry: до max_technical_attempts попыток вызова LLM + парсинга + валидации.
    TECHNICAL RETRY и PLAN RETRY независимы: технические ошибки внутри этой функции
    не увеличивают счётчик plan retry в вызывающем коде.

    Техническими ошибками считаются:
    - API exception, timeout, network error
    - пустой ответ модели
    - JSON parsing error
    - JSON root не object
    - отсутствует status
    - status не PASS и не FAIL
    - отсутствует score
    - score невозможно привести к числу
    - score вне диапазона 1-10
    - issues имеет некорректный тип, если поле присутствует

    Возвращает dict с ключами:
      - status: "PASS" | "FAIL"
      - score: int (1-10)
      - issues: list[dict] — каждый с type, severity, problem, fix
      - summary: str

    Возвращает None, если все technical attempts исчерпаны.
    В этом случае pipeline должен продолжить работу с текущим планом.
    """
    logger = logging.getLogger(__name__)

    prompt_text = load_prompt(settings, "story_check_prompt.txt")
    user_prompt = prompt_text.format(
        topic=topic,
        title=title,
        plan=json.dumps(plan_json, ensure_ascii=False, indent=2),
    )

    client = get_llm_client(settings, logger)
    system = "Ты редактор Яндекс Дзена. Возвращай только JSON без пояснений и markdown."

    for attempt in range(1, max_technical_attempts + 1):
        logger.info(f"[STORY_CHECK] Technical attempt {attempt}/{max_technical_attempts}")

        # Шаг 1: вызов LLM
        try:
            response = client.chat(
                system=system,
                user=user_prompt,
                temperature=0.3,
                max_tokens=3000,
            )
        except Exception as e:
            logger.error(f"[STORY_CHECK] Technical attempt {attempt} failed: API error: {e}")
            if attempt < max_technical_attempts:
                continue
            break

        # Шаг 2: проверка на пустой ответ
        if not response or not response.strip():
            logger.error(f"[STORY_CHECK] Technical attempt {attempt} failed: empty response")
            if attempt < max_technical_attempts:
                continue
            break

        # Шаг 3: парсинг JSON
        check = extract_json(response, logger=logger)
        if check is None:
            logger.error(f"[STORY_CHECK] Technical attempt {attempt} failed: invalid JSON")
            if attempt < max_technical_attempts:
                continue
            break

        # Шаг 4: семантическая валидация
        error = _validate_story_check(check, logger)
        if error:
            logger.error(f"[STORY_CHECK] Technical attempt {attempt} failed: {error}")
            if attempt < max_technical_attempts:
                continue
            break

        # Успех
        logger.info(f"[STORY_CHECK] Technical check succeeded: Status={check['status']} Score={check['score']}")

        critical_count = sum(1 for i in check.get("issues", []) if i.get("severity") == "critical")
        if critical_count:
            logger.info(f"[STORY_CHECK] Critical issues={critical_count}")

        return check

    # Все попытки исчерпаны
    logger.error(f"[STORY_CHECK] Technical check failed after {max_technical_attempts} attempts")
    logger.warning("[STORY_CHECK] Falling back to unchecked plan")
    return None