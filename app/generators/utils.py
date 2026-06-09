import json
import re


def load_prompt(settings, filename: str) -> str:
    """Загружает промт из app/prompts/"""
    path = settings.prompts_dir / filename
    return path.read_text(encoding="utf-8")


def parse_json_list(text: str) -> list[str]:
    """Парсит JSON массив строк из ответа AI (с fallback)"""

    # Попытка 1: прямой парсинг
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [str(x).strip() for x in data if x]
    except Exception:
        pass

    # Попытка 2: вытащить подстроку между [ и ]
    try:
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1:
            json_str = text[start: end + 1]
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