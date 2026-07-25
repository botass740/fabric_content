import base64
import logging
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

    def generate_image(self, prompt: str) -> bytes:
        """
        Генерирует изображение по промту.
        Возвращает PNG bytes.
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

        try:
            response = requests.post(
                self.endpoint,
                headers=headers,
                json=payload,
                timeout=120
            )
            response.raise_for_status()

            result = response.json()
            b64_data = result["data"][0]["b64_json"]
            image_bytes = base64.b64decode(b64_data)

            self.logger.info(f"Image generated successfully ({len(image_bytes)} bytes)")
            return image_bytes

        except Exception as e:
            self.logger.error(f"FLUX generation failed: {e}")
            raise