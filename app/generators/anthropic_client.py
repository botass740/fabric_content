import logging
import anthropic
from anthropic import DefaultHttpxClient


class AnthropicClient:
    """Клиент для Anthropic-совместимых шлюзов (freemodel.dev и т.п.).

    Интерфейс chat() совпадает с OpenRouterClient, поэтому генераторы
    работают с любым из них.
    """

    def __init__(
        self,
        auth_token: str,
        base_url: str,
        model: str,
        timeout_s: int = 120,
        logger: logging.Logger | None = None,
    ):
        self.model = model
        self.logger = logger or logging.getLogger(__name__)

        self.client = anthropic.Anthropic(
            auth_token=auth_token,
            base_url=base_url,
            timeout=timeout_s,
            http_client=DefaultHttpxClient(proxy=None),
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
        # temperature/top_p принимаем для совместимости интерфейса,
        # но не передаём: Opus 4.7 отвергает их с 400
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            parts = [block.text for block in response.content if block.type == "text"]
            return "".join(parts).strip()
        except Exception as e:
            self.logger.exception(f"Anthropic API error: {e}")
            raise
