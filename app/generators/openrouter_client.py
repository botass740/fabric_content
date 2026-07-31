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
        reasoning_effort: str = "",
        logger: logging.Logger | None = None,
    ):
        self.model = model
        # Для reasoning-моделей (gpt-5, o-серия): ограничивает объём скрытых
        # reasoning-токенов, чтобы они не съедали весь max_tokens и content
        # не приходил пустым. Для обычных моделей OpenRouter игнорирует поле.
        self.reasoning_effort = (reasoning_effort or "").strip().lower()
        self.logger = logger or logging.getLogger(__name__)

        # Создаём httpx клиент (прокси из HTTP_PROXY/HTTPS_PROXY env)
        http_client = httpx.Client(
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
            extra_body = {}
            if self.reasoning_effort:
                # OpenRouter-специфичное поле: {"reasoning": {"effort": "low"}}
                extra_body["reasoning"] = {"effort": self.reasoning_effort}

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
                extra_body=extra_body or None,
            )
            choice = response.choices[0]
            content = choice.message.content

            if not content or not content.strip():
                # Диагностика пустого ответа: finish_reason=length у reasoning-моделей
                # означает, что весь max_tokens ушёл на скрытый reasoning
                usage = getattr(response, "usage", None)
                self.logger.warning(
                    f"OpenRouter empty content: model={self.model} "
                    f"finish_reason={choice.finish_reason} usage={usage}"
                )
                return ""

            return content.strip()
        except Exception as e:
            self.logger.exception(f"OpenRouter API error: {e}")
            raise