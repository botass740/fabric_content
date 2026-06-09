import base64
import logging
import re
from datetime import datetime
from pathlib import Path
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont
import requests


logger = logging.getLogger(__name__)


def _make_slug(text: str, max_len: int = 40) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s]+", "_", text.strip())
    return text[:max_len]


def _wrap_text(text: str, max_chars: int = 22) -> list[str]:
    words = text.split()
    lines = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 <= max_chars:
            current = current + " " + word if current else word
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _make_placeholder(title: str, topic: str, save_path: Path) -> None:
    img = Image.new("RGB", (1024, 1024), color=(242, 242, 242))
    draw = ImageDraw.Draw(img)

    # Фон с простым градиентом (два прямоугольника)
    draw.rectangle([0, 0, 1024, 512], fill=(230, 240, 255))
    draw.rectangle([0, 512, 1024, 1024], fill=(242, 242, 242))

    # Попытка загрузить шрифт (Windows)
    font_large = None
    font_small = None
    font_paths = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
        "C:/Windows/Fonts/verdana.ttf",
    ]
    for fp in font_paths:
        if Path(fp).exists():
            try:
                font_large = ImageFont.truetype(fp, size=52)
                font_small = ImageFont.truetype(fp, size=32)
                break
            except Exception:
                continue

    if font_large is None:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Заголовок (крупно, по центру)
    title_lines = _wrap_text(title, max_chars=22)
    y = 200
    for line in title_lines:
        bbox = draw.textbbox((0, 0), line, font=font_large)
        w = bbox[2] - bbox[0]
        draw.text(((1024 - w) / 2, y), line, font=font_large, fill=(30, 30, 30))
        y += 65

    # Тема (мелко, снизу)
    topic_lines = _wrap_text(f"Тема: {topic}", max_chars=35)
    y = 750
    for line in topic_lines:
        bbox = draw.textbbox((0, 0), line, font=font_small)
        w = bbox[2] - bbox[0]
        draw.text(((1024 - w) / 2, y), line, font=font_small, fill=(100, 100, 100))
        y += 42

    img.save(str(save_path), "PNG")


def _make_openai_image(settings, topic: str, save_path: Path) -> bool:
    try:
        client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )

        prompt = (
            f"Реалистичная бытовая фотография-иллюстрация для блога о личных финансах. "
            f"Сюжет: {topic}. "
            f"Атмосфера: повседневная жизнь в квартире, магазине или офисе. "
            f"Без текста, без логотипов, без водяных знаков. "
            f"Естественный свет, эмоция, современная камера."
        )

        response = client.images.generate(
            model=settings.openai_image_model,
            prompt=prompt,
            size=settings.openai_image_size,
            response_format="b64_json",
            n=1,
        )

        # Попытка получить b64_json
        image_data = response.data[0]

        if hasattr(image_data, "b64_json") and image_data.b64_json:
            img_bytes = base64.b64decode(image_data.b64_json)
            save_path.write_bytes(img_bytes)
            return True

        # Fallback: если вернулся url
        if hasattr(image_data, "url") and image_data.url:
            resp = requests.get(image_data.url, timeout=30)
            resp.raise_for_status()
            save_path.write_bytes(resp.content)
            return True

        return False

    except Exception as e:
        logger.warning(f"OpenAI image generation failed: {e}")
        return False


def generate_cover(settings, *, topic: str, title: str) -> str | None:
    try:
        slug = _make_slug(title)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{slug}.png"
        save_path = settings.images_dir / filename

        if settings.has_openai_images:
            logger.info("Using OpenAI Images API")
            success = _make_openai_image(settings=settings, topic=topic, save_path=save_path)
            if not success:
                logger.warning("OpenAI failed, falling back to placeholder")
                _make_placeholder(title=title, topic=topic, save_path=save_path)
        else:
            logger.info("Using placeholder mode (no OpenAI key)")
            _make_placeholder(title=title, topic=topic, save_path=save_path)
        logger.info(f"Cover saved: {save_path}")
        return str(save_path)

    except Exception as e:
        logger.exception(f"Failed to generate cover: {e}")
        return None