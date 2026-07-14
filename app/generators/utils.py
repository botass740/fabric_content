import json
import logging
import re


def load_prompt(settings, filename: str) -> str:
    """Загружает промт из app/prompts/"""
    path = settings.prompts_dir / filename
    return path.read_text(encoding="utf-8")


def strip_markdown_fences(text: str) -> str:
    """Убирает markdown-ограничители (```json ... ```) из ответа LLM."""
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*\n', '', text)
    text = re.sub(r'\n```\s*$', '', text)
    return text.strip()


def extract_json(text: str, *, logger: logging.Logger | None = None) -> dict | None:
    """Извлекает JSON-объект из ответа LLM, устойчив к markdown-ограничителям.

    Пробует:
    1. Прямой парсинг после очистки markdown-ограничителей.
    2. Извлечение первого { ... } через re.DOTALL.
    3. Возвращает None, если ничего не подошло.
    """
    logger = logger or logging.getLogger(__name__)

    # Попытка 1: очистить ограничители и распарсить
    cleaned = strip_markdown_fences(text)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # Попытка 2: вытащить { ... } через regex
    match = re.search(r'\{.+\}', text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except Exception as e:
            logger.error(f"JSON из {match.group(0)[:500]}… не распарсен: {e}")
    else:
        logger.error(f"JSON-объект не найден в ответе. Первые 500 символов:\n{text[:500]}")

    return None


def parse_json_list(text: str) -> list[str]:
    """Парсит JSON массив строк из ответа AI (с fallback)"""

    # Попытка 0: очистить markdown-ограничители
    cleaned = strip_markdown_fences(text)

    # Попытка 1: прямой парсинг
    for candidate in (cleaned, text):
        try:
            data = json.loads(candidate)
            if isinstance(data, list):
                return [str(x).strip() for x in data if x]
        except Exception:
            pass

    # Попытка 2: вытащить подстроку между [ и ]
    for candidate in (cleaned, text):
        try:
            start = candidate.find("[")
            end = candidate.rfind("]")
            if start != -1 and end != -1:
                json_str = candidate[start: end + 1]
                data = json.loads(json_str)
                if isinstance(data, list):
                    return [str(x).strip() for x in data if x]
        except Exception:
            pass

    # Fallback: разбить по строкам и почистить
    lines = text.split("\n")
    result = []
    for line in lines:
        line = line.strip()
        line = re.sub(r"^[-•*]\s*", "", line)
        line = re.sub(r"^\d+[\.\)]\s*", "", line)
        line = line.strip('"\'')
        if line and len(result) < 50:
            result.append(line)
    return result