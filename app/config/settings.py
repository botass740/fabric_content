from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv
from typing import Optional
import os

# Cache for singleton
_settings = None

@dataclass
class Settings:
    telegram_bot_token: str = ""
    telegram_admin_id: Optional[int] = None
    telegram_api_base_url: str = ""
    openrouter_api_key: str = ""
    openrouter_model: str = "deepseek/deepseek-chat"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_timeout_s: int = 60
    openrouter_temperature: float = 0.85
    openrouter_top_p: float = 0.9
    openrouter_reasoning_effort: str = "low"
    llm_provider: str = "openrouter"
    anthropic_auth_token: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_model: str = "claude-opus-4-7"
    anthropic_timeout_s: int = 180
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_image_model: str = "gpt-image-1"
    openai_image_size: str = "1024x1024"
    data_dir: str = "./data"
    playwright_user_data_dir: str = "./playwright_profile"
    log_level: str = "INFO"
    sqlite_path: str = "./data/app.sqlite3"
    # Дзен/Playwright настройки
    flux_model: str = "black-forest-labs/flux.2-pro"
    flux_output_format: str = "png"
    # Дзен/Playwright настройки
    dzen_editor_url: str = "https://dzen.ru/"
    dzen_headless: bool = False
    dzen_default_timeout_ms: int = 30000
    dzen_publish_timeout_ms: int = 180000


    @property
    def project_root(self) -> Path:
        """Absolute path to the project root (parent of main.py or cwd)."""
        return Path.cwd().resolve()

    @property
    def data_dir_path(self) -> Path:
        return self.project_root / self.data_dir

    @property
    def articles_dir(self) -> Path:
        return self.data_dir_path / "articles"

    @property
    def images_dir(self) -> Path:
        return self.data_dir_path / "images"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir_path / "logs"

    @property
    def playwright_user_data_path(self) -> Path:
        return self.project_root / self.playwright_user_data_dir

    @property
    def sqlite_db_path(self) -> Path:
        """Absolute path to SQLite database."""
        return (self.project_root / self.sqlite_path).resolve()

    @property
    def prompts_dir(self) -> Path:
        return self.project_root / "app" / "prompts"
        
    @property
    def has_openai_images(self) -> bool:
        """Проверяет, настроен ли доступ к OpenAI для генерации изображений"""
        return bool(self.openai_api_key and self.openai_api_key.strip())

def get_settings() -> Settings:
    global _settings
    if _settings is None:
        load_dotenv()
        admin_id_str = os.getenv("TELEGRAM_ADMIN_ID", "")
        admin_id: Optional[int] = None
        if admin_id_str:
            try:
                admin_id = int(admin_id_str)
            except ValueError:
                pass
        _settings = Settings(
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_admin_id=admin_id,
            telegram_api_base_url=os.getenv("TELEGRAM_API_BASE_URL", ""),
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
            openrouter_model=os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat"),
            openrouter_base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            data_dir=os.getenv("DATA_DIR", "./data"),
            playwright_user_data_dir=os.getenv("PLAYWRIGHT_USER_DATA_DIR", "./playwright_profile"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            sqlite_path=os.getenv("SQLITE_PATH", "./data/app.sqlite3"),
            openrouter_timeout_s=int(os.getenv("OPENROUTER_TIMEOUT_S", "60")),
            openrouter_temperature=float(os.getenv("OPENROUTER_TEMPERATURE", "0.85")),
            openrouter_top_p=float(os.getenv("OPENROUTER_TOP_P", "0.9")),
            openrouter_reasoning_effort=os.getenv("OPENROUTER_REASONING_EFFORT", "low"),
            llm_provider=os.getenv("LLM_PROVIDER", "openrouter"),
            anthropic_auth_token=os.getenv("ANTHROPIC_AUTH_TOKEN", ""),
            anthropic_base_url=os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
            anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-opus-4-7"),
            anthropic_timeout_s=int(os.getenv("ANTHROPIC_TIMEOUT_S", "180")),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            openai_image_model=os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1"),
            openai_image_size=os.getenv("OPENAI_IMAGE_SIZE", "1024x1024"),
            flux_model=os.getenv("FLUX_MODEL", "black-forest-labs/flux.2-pro"),
            flux_output_format=os.getenv("FLUX_OUTPUT_FORMAT", "png"),
            dzen_editor_url=os.getenv("DZEN_EDITOR_URL", "https://dzen.ru/publisher/editor"),
            dzen_headless=os.getenv("DZEN_HEADLESS", "0") == "1",
            dzen_default_timeout_ms=int(os.getenv("DZEN_DEFAULT_TIMEOUT_MS", "30000")),
            dzen_publish_timeout_ms=int(os.getenv("DZEN_PUBLISH_TIMEOUT_MS", "180000")),
        )
    return _settings
