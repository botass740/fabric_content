import logging
from pathlib import Path
from datetime import datetime
import re
from PIL import Image, ImageDraw, ImageFont
import io

from app.generators.flux_client import FluxClient
from app.generators.article_analyzer import analyze_article_for_image
from app.prompts.image_templates import get_template


def _make_slug(text: str) -> str:
    """Создает безопасное имя файла из текста"""
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '_', text)
    return text[:40]


def _make_filename(title: str) -> str:
    """Генерирует имя файла: YYYYMMDD_HHMMSS_slug.png"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _make_slug(title)
    return f"{timestamp}_{slug}.png"


def _build_flux_prompt(template: dict, analysis: dict) -> str:
    """
    Подставляет данные анализа в шаблон промта.
    Сначала берет defaults из шаблона, затем перезаписывает данными из analysis.
    """
    # Начинаем с дефолтов шаблона
    params = template["defaults"].copy()

    # Перезаписываем русскими данными из анализа статьи
    if "subject" in analysis:
        params["subject"] = analysis["subject"]
    if "emotion" in analysis:
        params["emotion"] = analysis["emotion"]
    if "main_object" in analysis:
        params["main_object"] = analysis["main_object"]
    if "location" in analysis:
        params["location"] = analysis["location"]
    if "atmosphere" in analysis:
        params["atmosphere"] = analysis["atmosphere"]

    # Форматируем шаблон
    return template["prompt_template"].format(**params)


def _create_placeholder(title: str, size=(1280, 720)) -> bytes:
    """Создает PNG-плейсхолдер если FLUX недоступен"""
    img = Image.new("RGB", size, color="#F2F2F2")
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("arial.ttf", 60)
        font_sub = ImageFont.truetype("arial.ttf", 30)
    except Exception:
        font_title = ImageFont.load_default()
        font_sub = ImageFont.load_default()

    # Перенос заголовка по словам
    words = title.split()
    lines = []
    current_line = ""
    for word in words:
        test_line = current_line + " " + word if current_line else word
        if len(test_line) <= 24:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)

    # Рисуем текст по центру
    y_offset = size[1] // 2 - len(lines) * 35
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font_title)
        text_width = bbox[2] - bbox[0]
        x = (size[0] - text_width) // 2
        draw.text((x, y_offset), line, fill="#333333", font=font_title)
        y_offset += 70

    # Подпись внизу
    sub_text = "Обложка сгенерирована автоматически"
    bbox = draw.textbbox((0, 0), sub_text, font=font_sub)
    sub_width = bbox[2] - bbox[0]
    draw.text(((size[0] - sub_width) // 2, size[1] - 80), sub_text, fill="#999999", font=font_sub)

    # Конвертируем в bytes
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def generate_cover(settings, *, topic: str, title: str, content: str) -> str | None:
    """
    Главная функция генерации обложки.

    Пайплайн:
    1. Анализирует статью через LLM (определяет категорию, эмоцию, объекты)
    2. Выбирает подходящий шаблон из библиотеки
    3. Генерирует промт для FLUX на основе шаблона + анализа
    4. Создает изображение через FLUX (или placeholder при ошибке)
    5. Сохраняет в data/images/

    Возвращает путь к файлу или None при критической ошибке.
    """
    logger = logging.getLogger(__name__)

    # Генерируем имя файла
    filename = _make_filename(title)
    filepath = settings.images_dir / filename

    try:
        # ШАГ 1: Анализ статьи
        logger.info("Analyzing article for image generation...")
        analysis = analyze_article_for_image(settings, title=title, content=content)

        # ШАГ 2: Выбор шаблона
        category = analysis.get("category", "financial_mistake")
        template = get_template(category)
        logger.info(f"Selected template: {category}")

        # ШАГ 3: Построение промта для FLUX
        flux_prompt = _build_flux_prompt(template, analysis)
        logger.info(f"FLUX prompt: {flux_prompt[:150]}...")

        # ШАГ 4: Генерация через FLUX (если есть ключ OpenRouter)
        if settings.openrouter_api_key:
            try:
                client = FluxClient(
                    api_key=settings.openrouter_api_key,
                    model=settings.flux_model,
                    output_format=settings.flux_output_format,
                    logger=logger
                )
                image_bytes = client.generate_image(flux_prompt)

                # Сохраняем
                with open(filepath, "wb") as f:
                    f.write(image_bytes)

                logger.info(f"FLUX cover saved: {filepath}")
                return str(filepath)

            except Exception as e:
                logger.warning(f"FLUX failed ({e}), falling back to placeholder")
                # Продолжаем к placeholder

        # ШАГ 5: Placeholder (если FLUX не сработал или нет ключа)
        logger.info("Creating placeholder cover")
        placeholder_bytes = _create_placeholder(title)
        with open(filepath, "wb") as f:
            f.write(placeholder_bytes)

        logger.info(f"Placeholder cover saved: {filepath}")
        return str(filepath)

    except Exception as e:
        logger.exception(f"Cover generation failed completely: {e}")
        return None