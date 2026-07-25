"""
Стили обложек по категориям.

ВАЖНО: категория больше НЕ определяет содержимое сцены (кто/что/где).
Сцену полностью задаёт анализ статьи (см. article_analyzer.analyze_article_for_image).
Категория влияет ТОЛЬКО на киноязык кадра: атмосферу, цветокоррекцию,
характер света и композиционные предпочтения.

Каждый стиль — это художественная «оптика», сквозь которую снимается
центральная сцена статьи.
"""

IMAGE_STYLES = {
    "financial_mistake": {
        "description": "Финансовая ошибка, сожаление — тихая драма после решения",
        "grade": "desaturated cool tones, deep shadows, muted highlights",
        "light": "low-key natural light, single soft source, long shadows",
        "composition": "subject off-center, breathing room, shallow depth of field",
        "atmosphere": "quiet aftermath, weight of a decision that can't be undone",
    },
    "money_loss": {
        "description": "Резкая потеря, финансовый удар — момент шока",
        "grade": "cold grays with a single cold blue accent, crushed blacks",
        "light": "hard directional side light, tense contrast",
        "composition": "tight framing, slight tilt, negative space pressing in",
        "atmosphere": "sudden realization, ground giving way",
    },
    "smart_saving": {
        "description": "Верное решение, контроль — сдержанное облегчение",
        "grade": "warm neutral tones, gentle golden highlights, soft contrast",
        "light": "warm natural window light, clean and even",
        "composition": "balanced, calm, subject grounded in frame",
        "atmosphere": "quiet confidence, order restored",
    },
    "impulse_purchase": {
        "description": "Импульс и сомнение — момент между желанием и сожалением",
        "grade": "warm interior tones tipping into unease, uneven saturation",
        "light": "mixed artificial and window light, slightly restless",
        "composition": "handheld feel, subject caught mid-gesture",
        "atmosphere": "the second the excitement curdles into doubt",
    },
    "work_money": {
        "description": "Работа, усилие, карьера — сосредоточенность или усталость",
        "grade": "neutral tones with a muted teal-green cast, filmic",
        "light": "practical office/desk light plus cool daylight from a window",
        "composition": "environmental framing, subject small against workspace",
        "atmosphere": "grind and focus, the long haul",
    },
    "fraud_warning": {
        "description": "Опасность, обман — нарастающая тревога",
        "grade": "dark palette, deep shadows, one uneasy warm or red glow",
        "light": "low ambient light, screen or lamp as a hard local source",
        "composition": "subject partly in shadow, threat implied off-frame",
        "atmosphere": "something is wrong and only now being noticed",
    },
}

# Дефолтный стиль, если категория не распознана.
_DEFAULT_STYLE = "financial_mistake"


def get_template(category: str) -> dict:
    """Возвращает стиль по категории или дефолтный."""
    return IMAGE_STYLES.get(category, IMAGE_STYLES[_DEFAULT_STYLE])


def get_all_categories() -> list[str]:
    """Список всех доступных категорий (стилей)."""
    return list(IMAGE_STYLES.keys())
