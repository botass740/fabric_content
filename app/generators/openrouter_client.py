import logging
import httpx
from openai import OpenAI


class OpenRouterClient:

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout_s: int = 60,
        logger: logging.Logger | None = None,
    ):
        self.model = model
        self.logger = logger or logging.getLogger(__name__)

        # Создаём httpx клиент без системного прокси
        http_client = httpx.Client(
            proxy=None,
            timeout=timeout_s,
        )

        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
        )

    def chat(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.85,
        top_p: float = 0.9,
        max_tokens: int = 1200,
    ) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content
            return content.strip() if content else ""
        except Exception as e:
            self.logger.exception(f"OpenRouter API error: {e}")
            raise