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
    openrouter_api_key: str = ""
    openrouter_model: str = "deepseek/deepseek-chat"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_timeout_s: int = 60
    openrouter_temperature: float = 0.85
    openrouter_top_p: float = 0.9
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_image_model: str = "gpt-image-1"
    openai_image_size: str = "1024x1024"
    data_dir: str = "./data"
    playwright_user_data_dir: str = "./playwright_profile"
    log_level: str = "INFO"
    sqlite_path: str = "./data/app.sqlite3"

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
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            openai_image_model=os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1"),
            openai_image_size=os.getenv("OPENAI_IMAGE_SIZE", "1024x1024"),
        )
    return _settings
