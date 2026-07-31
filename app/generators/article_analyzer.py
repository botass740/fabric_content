import json
import logging
from app.generators.llm import get_llm_client
from app.prompts.image_templates import get_all_categories

# Обязательные поля сцены. Если LLM не вернула поле — подставляем нейтральный
# кинематографичный фолбэк, чтобы промт для FLUX всегда собирался.
_SCENE_FALLBACKS = {
    "scene": "a person pauses mid-motion, struck by a sudden realization",
    "character": "a person in their 40s, ordinary everyday look",
    "action": "frozen for a second, staring past the camera, processing what just happened",
    "environment": "a lived-in apartment kitchen in the evening, everyday clutter",
    "key_object": "a phone lying face up on the table",
    "camera": "medium shot",
    "lighting": "soft natural window light",
    "mood": "doubt and quiet unease",
    "color_palette": "muted warm tones with soft shadows",
}

# Допустимые типы кадра.
_ALLOWED_CAMERAS = ("close-up", "medium shot", "over shoulder", "cinematic wide")

# Дежурные объекты, которые нельзя ставить в центр сцены по умолчанию —
# только если статья буквально про них.
_BANNED_DEFAULT_OBJECTS = (
    "shopping bag", "shopping bags", "sale sign", "sale tag", "discount",
    "price tag", "red price", "wallet", "receipt", "receipts", "cash",
    "banknote", "banknotes", "pile of money", "stack of money", "coins",
)

_SCENE_FIELDS = ("scene", "character", "action", "environment", "key_object",
                 "camera", "lighting", "mood", "color_palette")


def analyze_article_for_image(settings, *, title: str, content: str) -> dict:
    """
    Определяет ЦЕНТРАЛЬНУЮ СЦЕНУ статьи для обложки-кинокадра.

    Концепция: обложка — не иллюстрация темы («статья про деньги»),
    а стоп-кадр самого эмоционального момента истории. Зритель должен
    спросить: «Что только что произошло?»

    Возвращает dict:
    {
        "category": "financial_mistake",  # ТОЛЬКО для стиля (свет/палитра/атмосфера), не для содержания сцены
        "scene": "...",          # краткое описание момента
        "character": "...",      # возраст, пол, типаж
        "action": "...",         # что герой делает именно сейчас
        "environment": "...",    # конкретное место
        "key_object": "...",     # один предмет, вокруг которого строится сцена
        "camera": "...",         # close-up / medium shot / over shoulder / cinematic wide
        "lighting": "...",       # естественный свет
        "mood": "...",           # эмоциональное состояние героя
        "color_palette": "..."   # определяется эмоцией истории
    }
    Все поля сцены — на английском (это промт для FLUX).
    """
    logger = logging.getLogger(__name__)

    categories = get_all_categories()
    categories_str = ", ".join(categories)

    system = (
        "Ты кинорежиссёр и художник-постановщик. Ты превращаешь историю в один "
        "драматический кадр — стоп-кадр из фильма. Возвращай только JSON без "
        "пояснений и markdown."
    )

    user = f"""Прочитай статью и найди её ЦЕНТРАЛЬНУЮ СЦЕНУ — один момент, который станет обложкой.

Заголовок: {title}

Статья: {content[:6000]}

Как выбрать момент:
- самый эмоциональный момент истории;
- момент максимального напряжения;
- момент, после которого хочется узнать, что было дальше.

Кадр ОБЯЗАН отвечать на три вопроса: КТО? ГДЕ? ЧТО ТОЛЬКО ЧТО ПРОИЗОШЛО?
Если выбранная сцена не отвечает на все три — выбери другой момент.

Жёсткие правила:
1. key_object бери ИЗ СОБЫТИЙ СТАТЬИ — предмет, вокруг которого реально крутится этот момент (например: телефон, конверт, свадебное приглашение, ключи, кружка, кассовый чек, договор, бензоколонка). НЕ ставь дежурные «кошелёк», «чеки», «пакеты», «деньги», если они не являются центром именно этой истории.
2. ЗАПРЕЩЕНЫ shopping bags, надписи SALE, скидочные таблички, красные ценники — кроме случая, когда статья буквально про них.
3. Деньги в кадре НЕ обязательны. Если история про отношения, стыд, подарки, работу, семью, конфликт — денег в кадре может не быть вовсе.
4. Лицо героя — главный эмоциональный элемент. Эмоции естественные: сомнение, стыд, растерянность, облегчение, тревога, неуверенность. НИКАКИХ постановочных улыбок, никакой позы «на камеру».
5. color_palette определяется ЭМОЦИЕЙ истории, а не её темой.
6. Если key_object — устройство с экраном (телефон, ноутбук, телевизор, банкомат), ОБЯЗАТЕЛЬНО опиши его положение относительно камеры физически точно. Экран либо не виден зрителю (крышка ноутбука к камере — это глухая матовая крышка БЕЗ экрана и без логотипов), либо виден под углом как мягкое размытое свечение без читаемого текста. Никогда не описывай интерфейс, надписи или цифры на экране.

Верни JSON. ВСЕ значения, кроме category, — НА АНГЛИЙСКОМ (это промт для генерации изображения):

- category (string): одна из [{categories_str}] — используется ТОЛЬКО для атмосферы, света и палитры, НЕ для содержания сцены
- scene (string): краткое описание момента, 1–2 предложения
- character (string): возраст, пол, типаж героя
- action (string): что герой делает именно сейчас, в эту секунду
- environment (string): конкретное место с бытовыми, «обжитыми» деталями
- key_object (string): ОДИН предмет, вокруг которого строится сцена
- camera (string): одно из: close-up, medium shot, over shoulder, cinematic wide
- lighting (string): естественный свет с конкретным источником (window light, dusk light, kitchen lamp, streetlight...)
- mood (string): эмоциональное состояние героя (естественное, без постановки)
- color_palette (string): палитра, вытекающая из эмоции истории

Только JSON, без markdown, без пояснений."""

    client = get_llm_client(settings, logger)

    response = client.chat(
        system=system,
        user=user,
        temperature=0.7,
        max_tokens=4096,
    )

    analysis = _parse_scene(response, logger)
    analysis = _normalize_scene(analysis, logger)

    logger.info(
        f"Central scene: category={analysis['category']} | "
        f"key_object={analysis['key_object'][:50]} | "
        f"camera={analysis['camera']} | mood={analysis['mood'][:50]}"
    )
    return analysis


def _parse_scene(response: str, logger: logging.Logger) -> dict:
    """Парсит JSON-ответ модели, терпимо к обёрткам/markdown."""
    try:
        parsed = json.loads(response)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    import re
    match = re.search(r"\{.+\}", response or "", re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    logger.warning(f"Failed to parse scene analysis, using fallback scene: {(response or '')[:200]}")
    return {}


def _normalize_scene(analysis: dict, logger: logging.Logger) -> dict:
    """Заполняет пропуски фолбэками, чистит запрещённые дефолтные объекты, валидирует camera/category."""
    result = {}

    for key in _SCENE_FIELDS:
        value = analysis.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()
        else:
            result[key] = _SCENE_FALLBACKS[key]

    # camera → одно из допустимых
    camera_low = result["camera"].lower()
    if not any(allowed in camera_low for allowed in _ALLOWED_CAMERAS):
        result["camera"] = "medium shot"

    # Защита от дежурного key_object: если модель всё же вернула банальщину,
    # но статья явно не про неё — заменяем на нейтральный фолбэк.
    key_object_low = result["key_object"].lower()
    if any(banned in key_object_low for banned in _BANNED_DEFAULT_OBJECTS):
        logger.warning(
            f"key_object hit banned default '{result['key_object']}', "
            f"replacing with neutral fallback"
        )
        result["key_object"] = _SCENE_FALLBACKS["key_object"]

    # category → только для стиля
    category = analysis.get("category")
    if category not in get_all_categories():
        category = "financial_mistake"
    result["category"] = category

    # scene пробрасываем как есть (текстовое описание момента, для логов/отладки)
    return result
