import base64
import logging
import time

import requests


class FluxClient:
    """
    Клиент для генерации изображений через FLUX.2 Pro на OpenRouter.
    Использует endpoint /api/v1/images (не chat/completions).
    """

    def __init__(self, api_key: str, model: str, output_format: str = "png", logger=None,
                 base_url: str = "https://openrouter.ai/api/v1"):
        self.api_key = api_key
        self.model = model
        self.output_format = output_format
        self.logger = logger or logging.getLogger(__name__)
        self.endpoint = base_url.rstrip("/") + "/images"

    def generate_image(self, prompt: str, attempts: int = 4) -> bytes:
        """
        Генерирует изображение по промту.
        Возвращает PNG bytes.

        Провайдер (Black Forest Labs) отклоняет часть генераций модерацией
        контента ("Content Moderated"), и это стохастически — один и тот же
        промт то проходит, то нет. Поэтому повторяем при нестабильных ошибках
        (4xx/5xx/сетевых) и логируем тело ответа (raise_for_status его теряет).
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model,
            "prompt": prompt,
            "output_format": self.output_format
        }

        self.logger.info(f"Generating image with FLUX: {prompt[:100]}...")

        last_status = None
        for attempt in range(1, attempts + 1):
            if attempt > 1:
                self.logger.info(
                    f"FLUX retry {attempt - 1}/{attempts - 1}, "
                    f"waiting {2 * attempt}s..."
                )
                time.sleep(2 * attempt)

            try:
                response = requests.post(
                    self.endpoint,
                    headers=headers,
                    json=payload,
                    timeout=120
                )
                last_status = response.status_code

                if response.status_code == 200:
                    result = response.json()
                    b64_data = result["data"][0]["b64_json"]
                    image_bytes = base64.b64decode(b64_data)
                    self.logger.info(
                        f"Image generated successfully ({len(image_bytes)} bytes)"
                    )
                    return image_bytes

                # Логируем тело ответа — оно объясняет причину отклонения.
                body = response.text[:2000]
                self.logger.warning(
                    f"FLUX attempt {attempt}/{attempts} failed: "
                    f"HTTP {response.status_code}: {body}"
                )

            except requests.exceptions.RequestException as e:
                self.logger.warning(
                    f"FLUX attempt {attempt}/{attempts} network error: {e}"
                )

        raise RuntimeError(
            f"FLUX generation failed after {attempts} attempts, "
            f"last HTTP status: {last_status}"
        )