import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional


class KnowledgeBase:
    """Читает и предоставляет данные из папки базы знаний.

    Папка определяется с приоритетом:
      1. Аргумент конструктора knowledge_dir
      2. Переменная окружения KNOWLEDGE_BASE_DIR
      3. Дефолт "knowledge_base"

    Загружает все JSON-файлы при инициализации. Ошибки чтения/парсинга
    отдельных файлов не фатальны — файл просто пропускается, остальные
    продолжают работать. Это гарантирует обратную совместимость: если
    база знаний отсутствует или повреждена, генератор работает как раньше.
    """

    def __init__(self, knowledge_dir: str | None = None):
        # Приоритет:
        # 1. Аргумент конструктора
        # 2. Переменная окружения KNOWLEDGE_BASE_DIR
        # 3. Дефолт "knowledge_base"
        if knowledge_dir:
            self.KNOWLEDGE_DIR = Path(knowledge_dir)
        else:
            env_dir = os.environ.get("KNOWLEDGE_BASE_DIR")
            self.KNOWLEDGE_DIR = Path(env_dir or "knowledge_base")
        self._data = {}
        self._logger = logging.getLogger(__name__)
        self._load_all()

    def _load_all(self):
        """Загрузить все JSON файлы при инициализации."""
        files = [
            "title_patterns.json",
            "vocabulary.json",
            "hooks.json",
            "article_structure.json",
            "topic_clusters.json",
            "meta.json",
        ]
        for filename in files:
            path = self.KNOWLEDGE_DIR / filename
            if not path.exists():
                self._logger.debug("Knowledge base file not found, skipped: %s", filename)
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    key = filename.replace(".json", "")
                    self._data[key] = json.load(f)
                self._logger.info("Knowledge base loaded: %s (%d KB)", filename, path.stat().st_size // 1024)
            except (json.JSONDecodeError, OSError) as e:
                self._logger.warning("Failed to load knowledge base file %s: %s", filename, e)

    def get_title_patterns(self) -> List[Dict]:
        """Вернуть список паттернов заголовков."""
        return self._data.get("title_patterns", {}).get("patterns", [])

    def get_recommended_pattern_mix(self) -> Dict[str, float]:
        """Рекомендуемое распределение паттернов."""
        return self._data.get("title_patterns", {}).get("recommended_mix", {})

    def get_power_words_titles(self, limit: int = 30) -> List[str]:
        """Топ слов для заголовков."""
        words = self._data.get("vocabulary", {}).get("top_words_in_titles", [])
        return [w["word"] for w in words[:limit] if isinstance(w, dict) and "word" in w]

    def get_power_bigrams(self, limit: int = 15) -> List[str]:
        """Топ биграммы."""
        bigrams = self._data.get("vocabulary", {}).get("power_bigrams", [])
        return [b["phrase"] for b in bigrams[:limit] if isinstance(b, dict) and "phrase" in b]

    def get_hooks_by_type(self, hook_type: str) -> Optional[Dict]:
        """Получить примеры хуков определённого типа."""
        hook_types = self._data.get("hooks", {}).get("hook_types", {})
        return hook_types.get(hook_type)

    def get_topic_cluster(self, cluster_name: str) -> Optional[Dict]:
        """Информация о тематическом кластере."""
        clusters = self._data.get("topic_clusters", {}).get("clusters", {})
        return clusters.get(cluster_name)

    def get_all_clusters(self) -> Dict:
        """Все кластеры."""
        return self._data.get("topic_clusters", {}).get("clusters", {})

    def get_channel_style(self, channel_slug: str) -> Optional[Dict]:
        """Стиль конкретного канала."""
        styles = self._data.get("article_structure", {}).get("by_channel_style", {})
        return styles.get(channel_slug)

    def is_loaded(self) -> bool:
        """True, если загружен хотя бы один файл базы знаний."""
        return bool(self._data)


# Singleton instance
_kb_instance = None


def get_knowledge_base(
    knowledge_dir: str | None = None,
) -> KnowledgeBase:
    """Получить синглтон базы знаний.

    Параметр knowledge_dir учитывается только при первом создании
    синглтона. Для смены тематики (переключения на другую папку)
    сначала вызовите reset_knowledge_base().
    """
    global _kb_instance
    if _kb_instance is None:
        _kb_instance = KnowledgeBase(knowledge_dir)
    return _kb_instance


def reset_knowledge_base() -> None:
    """Сбросить синглтон (для тестов или смены тематики)."""
    global _kb_instance
    _kb_instance = None
