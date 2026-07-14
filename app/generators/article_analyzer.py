import json
import logging
from app.generators.llm import get_llm_client
from app.prompts.image_templates import get_all_categories


def analyze_article_for_image(settings, *, title: str, content: str) -> dict:
    """
    Анализирует статью и определяет параметры для генерации обложки.

    Возвращает dict:
    {
        "category": "financial_mistake",
        "subject": "молодая женщина",
        "emotion": "сожаление",
        "main_object": "пустой кошелек и чеки на столе",
        "location": "кухня в квартире",
        "atmosphere": "осознание ошибки"
    }
    """
    logger = logging.getLogger(__name__)

    categories = get_all_categories()
    categories_str = ", ".join(categories)

    system = "Ты эксперт по визуальному сторителлингу для медиа. Возвращай только JSON без пояснений."

    user = f"""Проанализируй статью и определи какое изображение-обложку нужно сгенерировать.

Заголовок: {title}

Статья (начало): {content[:2000]}

Доступные категории: {categories_str}

Верни JSON со следующими полями:

- category (string): одна из доступных категорий, наиболее подходящая к статье
- subject (string): кто главный герой сцены (возраст, пол, краткое описание). На русском.
- emotion (string): какую эмоцию показывает (стресс/радость/сожаление/тревога/удивление). На русском.
- main_object (string): главный объект в кадре (деньги/телефон/документы/кошелек и т.п.). На русском.
- location (string): где происходит сцена (кухня/офис/магазин/улица). На русском.
- atmosphere (string): общая атмосфера (напряжение/облегчение/опасность/успех). На русском.

Ответ должен быть коротким и конкретным. Только JSON, без markdown, без пояснений."""

    client = get_llm_client(settings, logger)

    response = client.chat(
        system=system,
        user=user,
        temperature=0.6,
        max_tokens=400
    )

    # Парсим JSON
    try:
        analysis = json.loads(response)
    except Exception:
        import re
        match = re.search(r'\{.+\}', response, re.DOTALL)
        if match:
            analysis = json.loads(match.group(0))
        else:
            logger.warning(f"Failed to parse analysis, using defaults: {response[:200]}")
            analysis = {
                "category": "financial_mistake",
                "subject": "человек средних лет",
                "emotion": "озадаченность",
                "main_object": "документы на столе",
                "location": "домашний интерьер",
                "atmosphere": "финансовые раздумья"
            }

    logger.info(f"Article analyzed: category={analysis.get('category')}, emotion={analysis.get('emotion')}")
    return analysis