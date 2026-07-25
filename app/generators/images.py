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


# Обязательные требования к любому кадру — превращают картинку в кинокадр,
# а не в стоковую иллюстрацию.
_CINEMATIC_REQUIREMENTS = (
    "photorealistic, cinematic storytelling, film still, natural composition, "
    "lived-in environment, realistic facial expression, candid moment, not posing, "
    "no stock photo feeling, high-end photography, 35mm film look, shallow depth of field, "
    "physically accurate everyday objects and devices, anatomically correct hands, "
    "no text, no watermark, no logos, 16:9 aspect ratio"
)

# Чего кадр должен избегать по умолчанию (FluxClient не принимает negative prompt
# отдельным полем, поэтому включаем как «Avoid:» в тело промта).
# Вторая часть списка — типичные артефакты генерации, выдающие ИИ:
# экран на задней крышке ноутбука, кривые руки, нечитаемые буквы на дисплеях.
_AVOID = (
    "shopping bags, SALE signs, discount labels, red price tags, "
    "stock photo posing, fake smile, looking at camera, staged studio background, "
    "collage, infographic, text overlay, exaggerated cartoonish expression, "
    "screen or display on the back of a laptop lid, glowing logos on devices, "
    "readable text on screens, garbled letters, gibberish writing, "
    "extra fingers, deformed hands, warped or impossible objects, duplicated objects"
)


def _build_flux_prompt(style: dict, analysis: dict) -> str:
    """
    Собирает промт-кинокадр из центральной сцены статьи + визуального стиля категории.

    Содержание кадра (кто/что/где/что произошло) полностью берётся из analysis.
    Категория (style) задаёт только оптику: свет, палитру, композицию, атмосферу.
    """
    scene = analysis.get("scene", "")
    character = analysis["character"]
    action = analysis["action"]
    environment = analysis["environment"]
    key_object = analysis["key_object"]
    camera = analysis["camera"]
    lighting = analysis["lighting"]
    mood = analysis["mood"]
    color_palette = analysis["color_palette"]

    prompt = f"""Cinematic film still. {scene}

Subject: {character}, {action}. Facial expression carries the emotion of the scene.
Setting: {environment}.
Key object in frame: {key_object}.
Shot: {camera}, {camera_focus(camera)}.
Lighting: {lighting}; {style['light']}.
Color grade: {color_palette}; {style['grade']}.
Composition: {style['composition']}.
Mood: {mood}; {style['atmosphere']}.

{_CINEMATIC_REQUIREMENTS}.
Avoid: {_AVOID}."""

    return prompt.strip()


def camera_focus(camera: str) -> str:
    """Короткая подсказка фокуса под тип кадра."""
    camera = camera.lower()
    if "close-up" in camera:
        return "face fills the frame, eyes in sharp focus"
    if "over shoulder" in camera:
        return "framed from behind the subject, key object visible past the shoulder"
    if "cinematic wide" in camera:
        return "subject small within a telling environment"
    return "subject from the waist up, environment readable around them"


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
        # ШАГ 1: Анализ статьи → центральная сцена
        logger.info("Analyzing article for central scene...")
        analysis = analyze_article_for_image(settings, title=title, content=content)

        # ШАГ 2: Выбор визуального стиля (категория задаёт только оптику, не сцену)
        category = analysis.get("category", "financial_mistake")
        style = get_template(category)
        logger.info(f"Selected style: {category}")

        # ШАГ 3: Построение промта-кинокадра для FLUX
        flux_prompt = _build_flux_prompt(style, analysis)
        logger.info(f"FLUX prompt: {flux_prompt[:150]}...")

        # ШАГ 4: Генерация через FLUX (если есть ключ OpenRouter)
        if settings.openrouter_api_key:
            try:
                client = FluxClient(
                    api_key=settings.openrouter_api_key,
                    model=settings.flux_model,
                    output_format=settings.flux_output_format,
                    logger=logger,
                    base_url=settings.openrouter_base_url
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