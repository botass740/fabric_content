#!/usr/bin/env python3
"""
LLM-анализ агрегированных данных базы знаний.

Единственное место в проекте, где используется LLM для анализа.
LLM НЕ читает статьи — только агрегированные статистики из knowledge_base/.

Использование:
    from knowledge.llm_analyzer import LLMAnalyzer
    analyzer = LLMAnalyzer()
    result = await analyzer.analyze()
    analyzer.save_analysis(result)
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config.settings import get_settings
from app.generators.llm import get_llm_client

logger = logging.getLogger(__name__)


class LLMAnalyzer:
    """Финальный интеллектуальный анализ базы знаний через LLM.

    Загружает агрегированные данные из knowledge_base/, отправляет их
    в LLM для анализа и сохраняет результат.
    """

    KNOWLEDGE_BASE_DIR = "knowledge_base"

    def __init__(
        self,
        model_override: str | None = None,
        knowledge_dir: str | None = None,
    ):
        """Инициализировать анализатор.

        Args:
            model_override: Принудительная модель (поверх settings).
            knowledge_dir: Путь к папке базы знаний (по умолчанию
                KNOWLEDGE_BASE_DIR относительно корня проекта).
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.DEBUG)

        # Настройки
        self.settings = get_settings()
        self.logger.info(
            "LLM provider: %s, model: %s",
            self.settings.llm_provider,
            model_override or self.settings.anthropic_model,
        )

        # LLM клиент
        self._llm = get_llm_client(self.settings, logger=self.logger)

        # Переопределение модели, если нужно
        self._model_override = model_override

        # Путь к базе знаний
        if knowledge_dir:
            self._kb_path = Path(knowledge_dir)
        else:
            self._kb_path = (
                self.settings.project_root / self.KNOWLEDGE_BASE_DIR
            )

        # Загруженные данные
        self._data: dict[str, Any] = {}

        # Загрузить всё сразу
        self._load_knowledge_base()

    # ── загрузка данных ──────────────────────────────────────────────

    def _load_knowledge_base(self) -> dict[str, Any]:
        """Загрузить все JSON-файлы из knowledge_base/.

        Returns:
            Словарь {имя_файла_без_расширения: содержимое}.
        """
        self._data = {}
        kb_path = self._kb_path

        if not kb_path.is_dir():
            self.logger.warning("knowledge_base/ не найдена: %s", kb_path)
            return self._data

        for fpath in sorted(kb_path.iterdir()):
            if fpath.suffix != ".json":
                continue
            name = fpath.stem
            try:
                with open(fpath, encoding="utf-8") as f:
                    self._data[name] = json.load(f)
                self.logger.debug("Загружен %s.json (%d байт)", name, fpath.stat().st_size)
            except Exception as exc:
                self.logger.error("Ошибка загрузки %s: %s", fpath.name, exc)

        self.logger.info(
            "Загружено %d файлов из knowledge_base/", len(self._data)
        )
        return self._data

    # ── построение промпта ───────────────────────────────────────────

    def _create_analysis_prompt(self) -> str:
        """Собрать полный промпт для LLM из агрегированных данных.

        Returns:
            Текст промпта (system + user объединены).
        """
        data = self._data

        # ── Паттерны заголовков ──────────────────────────────────────
        title_patterns = data.get("title_patterns", {})
        patterns_text = ""
        for p in title_patterns.get("patterns", []):
            examples = "\n        ".join(p.get("examples", [])[:3])
            patterns_text += (
                f"\n  - {p['name']} ({p.get('frequency', 0)*100:.1f}%): {p.get('description', '')}\n"
                f"    Шаблон: {p.get('template', '')}\n"
                f"    Примеры:\n        {examples}\n"
            )

        recommended_mix = title_patterns.get("recommended_mix", {})
        if recommended_mix:
            patterns_text += "\n  Рекомендуемая пропорция:\n"
            for pat_name, frac in sorted(
                recommended_mix.items(), key=lambda x: -x[1]
            ):
                patterns_text += f"    {pat_name}: {frac*100:.0f}%\n"

        # ── Словарь ──────────────────────────────────────────────────
        vocab = data.get("vocabulary", {})

        title_words = vocab.get("top_words_in_titles", [])[:30]
        title_words_text = ", ".join(
            f"{w['word']} ({w['count']})" for w in title_words
        )

        text_words = vocab.get("top_words_in_texts", [])[:30]
        text_words_text = ", ".join(
            f"{w['word']} ({w['count']})" for w in text_words
        )

        bigrams = vocab.get("power_bigrams", [])[:15]
        bigrams_text = ", ".join(
            f'"{b["phrase"]}" ({b["count"]})' for b in bigrams
        )

        trigrams = vocab.get("power_trigrams", [])[:10]
        trigrams_text = ", ".join(
            f'"{t["phrase"]}" ({t["count"]})' for t in trigrams
        )

        finance_terms = vocab.get("finance_terms", [])
        emotion_words = vocab.get("emotion_words", [])

        # ── Хуки ─────────────────────────────────────────────────────
        hooks = data.get("hooks", {})
        hooks_text = ""
        for htype, hinfo in hooks.get("hook_types", {}).items():
            examples = "\n        ".join(hinfo.get("examples", [])[:2])
            hooks_text += (
                f"\n  - {htype}: count={hinfo.get('count', 0)}, "
                f"effectiveness={hinfo.get('effectiveness', '')}\n"
                f"    Шаблон: {hinfo.get('template', '')}\n"
                f"    Примеры:\n        {examples}\n"
            )

        # ── Структура статей ─────────────────────────────────────────
        structure = data.get("article_structure", {})
        rec_len = structure.get("recommended_length", {})
        rec_struct = structure.get("recommended_structure", {})

        structure_text = (
            f"\n  Длина: {rec_len.get('min_words', 0)}-{rec_len.get('max_words', 0)} слов, "
            f"оптимально {rec_len.get('optimal_words', 0)} слов\n"
            f"  Абзацы: {rec_struct.get('paragraphs_min', 0)}-{rec_struct.get('paragraphs_max', 0)}, "
            f"оптимально {rec_struct.get('paragraphs_optimal', 0)}\n"
            f"  Подзаголовки: {'да' if rec_struct.get('use_headers', False) else 'нет'}, "
            f"оптимально {rec_struct.get('headers_count_optimal', 0)}\n"
            f"  Изображения: {'да' if rec_struct.get('use_images', False) else 'нет'}, "
            f"оптимально {rec_struct.get('images_count_optimal', 0)}\n"
        )

        # Стили по каналам
        by_channel = structure.get("by_channel_style", {})
        channels_text = ""
        for slug, info in sorted(by_channel.items()):
            desc = info.get("description", "")
            channels_text += (
                f"\n  - {slug}: {info.get('style', '')}, "
                f"~{info.get('avg_words', 0):.0f} слов, "
                f"паттерн {info.get('typical_pattern', '')}"
                f"{' — ' + desc if desc else ''}"
            )

        # ── Темы / кластеры ──────────────────────────────────────────
        clusters_data = data.get("topic_clusters", {})
        clusters_text = ""
        for cname, cinfo in sorted(
            clusters_data.get("clusters", {}).items(),
            key=lambda x: -x[1].get("percentage", 0),
        ):
            top_w = ", ".join(
                f"{w['word']} ({w['frequency']})"
                for w in cinfo.get("top_words", [])[:3]
            )
            examples = "\n        ".join(cinfo.get("example_titles", [])[:2])
            clusters_text += (
                f"\n  - {cname}: {cinfo.get('percentage', 0):.1f}% "
                f"({cinfo.get('article_count', 0)} статей)\n"
                f"    Ключевые слова: {top_w}\n"
                f"    Примеры:\n        {examples}\n"
            )

        overlap = clusters_data.get("overlap_analysis", {})
        combos = overlap.get("most_common_combinations", [])
        combos_text = ""
        for c in combos[:5]:
            combos_text += (
                f"  - {' + '.join(c['clusters'])}: {c['count']} статей\n"
            )

        # ── Собираем всё в промпт ────────────────────────────────────
        prompt = f"""Ты — аналитик контента для финансового Telegram-канала в Дзене.
Перед тобой агрегированная статистика 560 успешных статей с 34 финансовых каналов Дзена.

Твоя задача: дать конкретные рекомендации для генерации новых статей на основе паттернов успешных публикаций.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ДАННЫЕ ДЛЯ АНАЛИЗА
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. ПАТТЕРНЫ ЗАГОЛОВКОВ (всего {len(title_patterns.get('patterns', []))} паттернов, проанализировано {title_patterns.get('total_analyzed', 560)} статей):
{patterns_text}

2. СЛОВАРЬ:

   Топ-30 слов в заголовках (слово: частота):
   {title_words_text}

   Топ-30 слов в текстах:
   {text_words_text}

   Топ-15 биграмм:
   {bigrams_text}

   Топ-10 триграмм:
   {trigrams_text}

   Финансовые термины ({len(finance_terms)}): {', '.join(finance_terms[:20])}

   Эмоциональные слова ({len(emotion_words)}): {', '.join(emotion_words)}

3. ХУКИ (классификация первых предложений 560 статей):
{hooks_text}

4. СТРУКТУРА СТАТЕЙ:
{structure_text}

   Стили по каналам:{channels_text}

5. ТЕМЫ (9 кластеров, {clusters_data.get('total_articles', 560)} статей, среднее {overlap.get('average_clusters_per_article', 0):.1f} кластеров на статью):
{clusters_text}

   Топ-5 комбинаций кластеров:
{combos_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ВОПРОСЫ ДЛЯ АНАЛИЗА
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

На основе этих данных ответь на следующие вопросы:

1. ЗАГОЛОВКИ
   - Какие 3 паттерна заголовков самые эффективные?
   - Какие комбинации паттернов работают лучше всего?
   - Какие слова/фразы обязательно использовать в заголовках?
   - Чего избегать в заголовках?

2. ТЕМЫ
   - Какие 3 темы доминируют и почему?
   - Какие комбинации тем встречаются чаще всего?
   - Есть ли недостаточно освещённые темы (возможности)?
   - Какие темы лучше НЕ трогать (перенасыщены)?

3. СТИЛЬ НАПИСАНИЯ
   - Какой стиль преобладает (аналитика/истории/инструкции)?
   - Оптимальная длина статьи для максимального вовлечения?
   - Использовать подзаголовки или нет? Сколько?
   - Роль изображений в статье?

4. ХУКИ
   - Какой тип хука самый сильный?
   - Как правильно начинать статью (первые 2 предложения)?
   - Примеры идеальных хуков для разных типов статей?

5. СЛОВАРЬ
   - Какие слова создают эмоциональный отклик?
   - Какие финансовые термины обязательны?
   - Какие биграммы/триграммы усиливают заголовок?

6. ГЛАВНЫЕ РЕКОМЕНДАЦИИ
   - ТОП-5 правил для генерации заголовков
   - ТОП-5 правил для структуры статьи
   - ТОП-5 правил для выбора темы
   - Что делать ОБЯЗАТЕЛЬНО
   - Что делать НИКОГДА

Формат ответа: структурированный текст с конкретными примерами и цифрами.
Избегай общих фраз типа «используй эмоции».
Давай конкретику: «используй слово X в заголовке, потому что оно встречается в Y% успешных статей».
"""
        return prompt

    # ── анализ ───────────────────────────────────────────────────────

    async def analyze(self) -> dict[str, Any]:
        """Запустить анализ через LLM.

        Returns:
            Словарь с результатами анализа.
        """
        start_time = datetime.now(timezone.utc)

        prompt = self._create_analysis_prompt()
        prompt_tokens_est = len(prompt) // 4  # грубая оценка

        self.logger.info(
            "Промпт собран: ~%d символов, ~%d токенов (оценка)",
            len(prompt),
            prompt_tokens_est,
        )
        print(f"  Промпт: ~{len(prompt):,} символов")
        print()

        # Выбрать модель
        model = self._model_override or self.settings.anthropic_model
        self.logger.info("Отправка запроса в LLM (модель: %s)...", model)

        # Сохраним промпт для воспроизводимости
        self._last_prompt = prompt

        try:
            # chat() — синхронный, запускаем в потоке
            analysis_text = await asyncio.to_thread(
                self._llm.chat,
                system=(
                    "Ты — аналитик контента для финансового Telegram-канала в Дзене. "
                    "Отвечай структурированно, с цифрами и примерами. "
                    "Используй русский язык."
                ),
                user=prompt,
                temperature=0.3,
                max_tokens=4000,
            )

            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            completion_tokens_est = len(analysis_text) // 4

            self.logger.info(
                "Анализ завершён за %.1f с. ~%d токенов ответа",
                elapsed,
                completion_tokens_est,
            )

            result = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "model": model,
                "prompt_tokens": prompt_tokens_est,
                "completion_tokens": completion_tokens_est,
                "total_tokens_estimate": prompt_tokens_est + completion_tokens_est,
                "analysis": analysis_text,
            }
            return result

        except Exception as exc:
            self.logger.exception("Ошибка при вызове LLM: %s", exc)
            raise

    # ── сохранение результатов ───────────────────────────────────────

    def save_analysis(self, result: dict[str, Any]) -> None:
        """Сохранить результат анализа в файлы.

        Создаёт:
          - knowledge_base/llm_analysis.json (полные данные)
          - knowledge_base/RECOMMENDATIONS.md (читаемая версия)

        Args:
            result: Словарь из analyze().
        """
        analysis_text = result.get("analysis", "")

        # Извлечь ключевые рекомендации (строки с ТОП-5, ОБЯЗАТЕЛЬНО, НИКОГДА)
        key_recommendations = self._extract_recommendations(analysis_text)

        # JSON-версия
        json_data = {
            "generated_at": result.get("generated_at", ""),
            "model": result.get("model", ""),
            "tokens": {
                "prompt": result.get("prompt_tokens", 0),
                "completion": result.get("completion_tokens", 0),
                "total": result.get("total_tokens_estimate", 0),
            },
            "analysis_text": analysis_text,
            "key_recommendations": key_recommendations,
        }

        json_path = self._kb_path / "llm_analysis.json"
        self._kb_path.mkdir(parents=True, exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        self.logger.info("Сохранён %s (%d байт)", json_path, json_path.stat().st_size)

        # Markdown-версия
        md_path = self._kb_path / "RECOMMENDATIONS.md"
        md_content = self._build_markdown(result, key_recommendations)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        self.logger.info("Сохранён %s (%d байт)", md_path, md_path.stat().st_size)

    @staticmethod
    def _extract_recommendations(text: str) -> list[str]:
        """Извлечь ключевые рекомендации из текста анализа.

        Ищет строки, содержащие маркеры ТОП-5, ОБЯЗАТЕЛЬНО, НИКОГДА.

        Args:
            text: Текст анализа от LLM.

        Returns:
            Список строк-рекомендаций.
        """
        lines = text.split("\n")
        recs = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            # Строки с маркерами рекомендаций
            if re.search(
                r"(ТОП-5|ТОП 5|ОБЯЗАТЕЛЬНО|НИКОГДА|"
                r"правил[оа].*заголовк|правил[оа].*структур|"
                r"правил[оа].*тему|Do\s*:|Don'ts?\s*:|"
                r"Главн[аяое]?\s*рекомендаци)",
                stripped,
                re.IGNORECASE,
            ):
                recs.append(stripped)
        return recs[:20]  # не больше 20 строк

    @staticmethod
    def _build_markdown(
        result: dict[str, Any],
        recommendations: list[str],
    ) -> str:
        """Построить Markdown-файл с рекомендациями.

        Args:
            result: Словарь из analyze().
            recommendations: Список извлечённых рекомендаций.

        Returns:
            Markdown-текст.
        """
        analysis_text = result.get("analysis", "")

        lines = [
            "# Рекомендации по генерации контента\n",
            f"Сгенерировано: {result.get('generated_at', '')[:19]}",
            f"Модель: {result.get('model', '')}",
            f"Токенов: {result.get('total_tokens_estimate', 0)}",
            "",
            "---",
            "",
            "## Ключевые рекомендации\n",
        ]

        if recommendations:
            for rec in recommendations:
                lines.append(f"- {rec}")
        else:
            lines.append("(автоматическое извлечение не дало результатов — см. полный текст ниже)")

        lines.extend([
            "",
            "---",
            "",
            "## Полный анализ\n",
            "",
            analysis_text,
            "",
        ])

        return "\n".join(lines)

    # ── утилиты ──────────────────────────────────────────────────────

    @property
    def last_prompt(self) -> str | None:
        """Последний отправленный промпт (для отладки)."""
        return getattr(self, "_last_prompt", None)