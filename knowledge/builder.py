#!/usr/bin/env python3
"""
Knowledge Builder — модуль построения базы знаний из статистического отчёта.

Читает:
  - data/statistics_report.json (статистический анализ корпуса)
  - data/research.db (тексты статей для хуков и кластеризации)

Создаёт:
  knowledge_base/*.json — 5 файлов базы знаний
"""

import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any


class KnowledgeBuilder:
    """Построитель базы знаний из статанализа и текстов статей."""

    KNOWLEDGE_BASE_DIR = "knowledge_base"
    STATISTICS_PATH = "data/statistics_report.json"
    DB_PATH = "data/research.db"

    # Ключевые слова для тематических кластеров (build_topic_clusters)
    CLUSTER_KEYWORDS: dict[str, list[str]] = {
        "investments": [
            "акции", "облигации", "дивиденды", "портфель",
            "инвестиции", "биржа", "фонд", "etf", "брокер",
            "доходность", "риск", "волатильность",
        ],
        "banking": [
            "вклад", "депозит", "ставка", "процент", "банк",
            "кредит", "ипотека", "карта", "счёт", "овердрафт",
            "кэшбэк", "рефинансирование",
        ],
        "budget": [
            "бюджет", "расходы", "доходы", "экономия", "накопления",
            "зарплата", "трата", "семья", "планирование", "учёт",
            "сбережения", "финплан",
        ],
        "macro": [
            "инфляция", "рубль", "доллар", "цб", "ключевая",
            "экономика", "цены", "рост", "курс", "девальвация",
            "дефицит", "бюджет страны", "нефть", "золото",
        ],
        "personal_finance": [
            "пенсия", "льготы", "налог", "вычет", "субсидия",
            "маткапитал", "пособие", "ндфл", "социальный",
            "выплата", "компенсация",
        ],
        "fraud": [
            "мошенник", "схема", "развод", "обман", "пирамида",
            "осторожно", "предупреждение", "фишинг", "скам",
            "кидалово", "афера", "лохотрон",
        ],
        "stories": [
            "дед", "бабушка", "мать", "отец", "сын", "дочь",
            "внук", "семья", "история", "жизнь", "годы",
            "пенсионер", "родители", "дети",
        ],
        "real_estate": [
            "квартира", "ипотека", "недвижимость", "жильё",
            "покупка", "продажа", "аренда", "ремонт",
            "метры", "жкх", "коммуналка",
        ],
        "salary_career": [
            "зарплата", "работа", "карьера", "вакансия",
            "резюме", "собеседование", "увольнение",
            "повышение", "премия", "бонус",
        ],
    }

    # Финансовые термины для vocabulary.json (build_vocabulary)
    FINANCE_TERMS_SET: set[str] = {
        "деньги", "рубль", "рублей", "банк", "кредит", "ипотека",
        "вклад", "инвестиции", "акции", "ставка", "инфляция",
        "бюджет", "доход", "зарплата", "пенсия", "налог", "процент",
        "капитал", "сбережения", "экономия", "накопления", "облигации",
        "дивиденды", "портфель", "валюта", "доллар", "евро",
    }

    # Эмоциональные слова для vocabulary.json (build_vocabulary)
    EMOTION_WORDS_SET: set[str] = {
        "страх", "риск", "потери", "выгода", "прибыль", "успех",
        "ошибка", "проблема", "кризис", "возможность", "шанс",
        "угроза", "важно", "срочно", "внимание", "осторожно",
        "наконец", "впервые", "разорение", "банкротство", "обман",
    }

    # Описания стилей каналов для article_structure.json (build_article_structure)
    CHANNEL_STYLES: dict[str, dict[str, str]] = {
        "igorfaynman": {
            "style": "analytical_news",
            "typical_pattern": "colon_split",
            "description": "Короткие аналитические заметки на актуальные темы",
        },
        "vzoprodengi": {
            "style": "storytelling",
            "typical_pattern": "personal_story",
            "description": "Длинные истории о людях и деньгах с моралью",
        },
        "gazprombank": {
            "style": "educational",
            "typical_pattern": "how_to",
            "description": "Короткие образовательные материалы и инструкции",
        },
        "myfincons": {
            "style": "professional_advice",
            "typical_pattern": "question",
            "description": "Профессиональные советы финансового консультанта",
        },
        "pavelrakov": {
            "style": "expert_opinion",
            "typical_pattern": "colon_split",
            "description": "Экспертное мнение по рынкам и инвестициям",
        },
        "igorrybakov": {
            "style": "storytelling_advice",
            "typical_pattern": "personal_story",
            "description": "Истории из жизни с элементами финансового консультирования",
        },
        "azbukadeneg": {
            "style": "educational_short",
            "typical_pattern": "how_to",
            "description": "Короткие обучающие заметки по финансовой грамотности",
        },
        "navigator_finans": {
            "style": "guide",
            "typical_pattern": "colon_split",
            "description": "Подробные гиды и разборы финансовых продуктов",
        },
        "kapitalist": {
            "style": "micro_notes",
            "typical_pattern": "other",
            "description": "Короткие заметки и цитаты по финансам",
        },
        "ekonomim_dengi": {
            "style": "longread_economics",
            "typical_pattern": "colon_split",
            "description": "Длинные разборы экономических тем и макростатистики",
        },
        "budniminimalista": {
            "style": "minimalist_lifestyle",
            "typical_pattern": "how_to",
            "description": "Истории и советы о минимализме и разумном потреблении",
        },
    }

    def __init__(self) -> None:
        """Инициализация: создаёт папку knowledge_base, загружает статистику,
        подключается к БД, настраивает логгер."""
        self.logger = self._setup_logger()
        self._ensure_knowledge_base_dir()
        self.stats: dict[str, Any] = self._load_statistics()
        self.db_conn: sqlite3.Connection = self._connect_db()
        self.logger.info("KnowledgeBuilder инициализирован")

    # ── helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _setup_logger() -> logging.Logger:
        """Настроить и вернуть логгер."""
        logger = logging.getLogger("KnowledgeBuilder")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
            )
            logger.addHandler(handler)
        return logger

    def _ensure_knowledge_base_dir(self) -> None:
        """Создать директорию knowledge_base/ если не существует."""
        os.makedirs(self.KNOWLEDGE_BASE_DIR, exist_ok=True)
        self.logger.info("Директория %s готова", self.KNOWLEDGE_BASE_DIR)

    def _load_statistics(self) -> dict[str, Any]:
        """Загрузить statistics_report.json."""
        path = self.STATISTICS_PATH
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.logger.info(
                "Загружена статистика: %d статей, %d каналов",
                data.get("corpus", {}).get("total_articles", 0),
                data.get("corpus", {}).get("total_channels", 0),
            )
            return data
        except FileNotFoundError:
            self.logger.warning("Файл статистики %s не найден, используется пустой словарь", path)
            return {}
        except json.JSONDecodeError as e:
            self.logger.error("Ошибка парсинга %s: %s", path, e)
            return {}

    def _connect_db(self) -> sqlite3.Connection:
        """Подключиться к research.db."""
        path = self.DB_PATH
        try:
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            self.logger.info("Подключена БД: %s", path)
            return conn
        except sqlite3.Error as e:
            self.logger.error("Ошибка подключения к БД %s: %s", path, e)
            raise

    def _save(self, filename: str, data: dict[str, Any]) -> None:
        """Сохранить словарь в knowledge_base/{filename}.json."""
        path = os.path.join(self.KNOWLEDGE_BASE_DIR, filename)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            size = os.path.getsize(path)
            self.logger.info("Сохранён %s (%d байт)", filename, size)
        except OSError as e:
            self.logger.error("Ошибка записи %s: %s", path, e)

    def _build_timestamp(self) -> str:
        """Вернуть текущую метку времени в ISO-формате."""
        return datetime.now(timezone.utc).isoformat()

    # ── build_title_patterns ─────────────────────────────────────────

    def build_title_patterns(self) -> dict[str, Any]:
        """
        Построить title_patterns.json из статистики.

        Берёт данные из self.stats['title_patterns']['patterns'] и обогащает
        их шаблонами и советами. Добавляет recommended_mix.
        """
        self.logger.info("=== build_title_patterns ===")
        start = time.time()

        patterns_raw = self.stats.get("title_patterns", {}).get("patterns", {})
        total_analyzed = self.stats.get("corpus", {}).get("total_articles", 0)

        # Шаблоны и советы для каждого паттерна
        PATTERN_TEMPLATES: dict[str, dict[str, str]] = {
            "colon_split": {
                "template": "{ТЕМА}: {ДЕТАЛИ_ИЛИ_ВОПРОС}",
                "tips": "Работает для аналитических статей. Ставь конкретную тему слева от двоеточия.",
            },
            "personal_story": {
                "template": "{РОДСТВЕННИК/ВОЗРАСТ} {ДЕЙСТВИЕ} {СУММА/СИТУАЦИЯ}. {РЕЗУЛЬТАТ}",
                "tips": "Самый вовлекающий формат для vzoprodengi-стиля. Герой = пенсионер/бабушка/дед. Обязательно добавить неожиданный поворот.",
            },
            "question": {
                "template": "{ВОПРОС_С_КОНКРЕТИКОЙ}?",
                "tips": "Вопрос должен быть конкретным, с цифрами или датами.",
            },
            "how_to": {
                "template": "Как {ДЕЙСТВИЕ} {РЕЗУЛЬТАТ/ЦЕЛЬ}",
                "tips": "Обещай конкретный результат. Избегай 'как стать богатым' — слишком абстрактно.",
            },
            "number_list": {
                "template": "{ЧИСЛО} {способов/ошибок/правил/причин} {ТЕМА}",
                "tips": "Используй нечётные числа (5, 7) — лучше кликабельность чем чётные.",
            },
            "money_amount": {
                "template": "{ДЕЙСТВИЕ} {СУММА}: {КОНТЕКСТ/РЕЗУЛЬТАТ}",
                "tips": "Суммы привлекают внимание. Указывай реальные, узнаваемые цифры.",
            },
            "age_mention": {
                "template": "В {ВОЗРАСТ} лет {НЕОЖИДАННОЕ_ДЕЙСТВИЕ}",
                "tips": "Возраст 60+ цепляет лучше. Действие должно быть нетипичным для возраста.",
            },
            "quote": {
                "template": '"{ЦИТАТА}": {ОБЪЯСНЕНИЕ}',
                "tips": "Цитата должна быть яркой и самодостаточной. Работает для личных историй.",
            },
            "other": {
                "template": "{СВОБОДНЫЙ_ФОРМАТ}",
                "tips": "Прочие форматы. Анализируй вручную для выявления новых паттернов.",
            },
        }

        patterns: list[dict[str, Any]] = []
        for name, info in patterns_raw.items():
            count = info.get("count", 0)
            f_total = total_analyzed or 1
            frequency = round(count / f_total, 3)
            examples = info.get("examples", [])[:3]
            tmpl = PATTERN_TEMPLATES.get(name, {})
            pattern: dict[str, Any] = {
                "name": name,
                "description": self._pattern_description(name),
                "frequency": frequency,
                "count": count,
                "examples": examples,
                "template": tmpl.get("template", ""),
                "tips": tmpl.get("tips", ""),
            }
            patterns.append(pattern)

        # Сортируем по убыванию частоты
        patterns.sort(key=lambda p: p["frequency"], reverse=True)

        # Убираем "other" из recommended_mix, перераспределяем
        mix_patterns = [p for p in patterns if p["name"] != "other"]
        total_mix = sum(p["frequency"] for p in mix_patterns) or 1
        recommended_mix = {
            p["name"]: round(p["frequency"] / total_mix, 2)
            for p in mix_patterns
        }

        result: dict[str, Any] = {
            "generated_at": self._build_timestamp(),
            "total_analyzed": total_analyzed,
            "patterns": patterns,
            "recommended_mix": recommended_mix,
            "notes": "Паттерны не взаимоисключающие. Один заголовок может содержать и сумму, и вопрос.",
        }

        self._save("title_patterns.json", result)
        self.logger.info("build_title_patterns: %.2f с", time.time() - start)
        return result

    @staticmethod
    def _pattern_description(name: str) -> str:
        """Вернуть описание паттерна по его имени."""
        descriptions = {
            "colon_split": "Тема: детали или вопрос",
            "personal_story": "Личная история с деньгами",
            "question": "Вопрос читателю",
            "how_to": "Инструкция",
            "number_list": "Списочная статья",
            "money_amount": "Конкретная сумма в заголовке",
            "age_mention": "Возраст в заголовке",
            "quote": "Цитата в заголовке",
            "other": "Прочие форматы",
        }
        return descriptions.get(name, name)

    # ── build_vocabulary ─────────────────────────────────────────────

    def build_vocabulary(self) -> dict[str, Any]:
        """
        Построить vocabulary.json из статистики.

        Берёт top_words_in_titles, top_words_in_texts, ngrams
        из self.stats и разделяет слова на финансовые термины и
        эмоционально окрашенные.
        """
        self.logger.info("=== build_vocabulary ===")
        start = time.time()

        word_freq = self.stats.get("word_frequency", {})
        ngrams = self.stats.get("ngrams", {})

        top_words_in_titles = word_freq.get("top_words_in_titles", [])[:50]
        top_words_in_texts = word_freq.get("top_words_in_texts", [])[:100]
        top_bigrams = ngrams.get("top_bigrams", [])[:30]
        top_trigrams = ngrams.get("top_trigrams", [])[:20]

        # Финансовые термины: пересечение топа слов с FINANCE_TERMS_SET
        all_text_words = word_freq.get("top_words_in_texts", [])
        finance_terms = [
            w["word"] for w in all_text_words
            if w["word"].lower() in self.FINANCE_TERMS_SET
        ]
        # Если в топе нашлось мало — добавляем полный справочный список
        if len(finance_terms) < 10:
            finance_terms = sorted(self.FINANCE_TERMS_SET)

        # Эмоциональные слова: пересечение топа слов с EMOTION_WORDS_SET
        emotion_words = [
            w["word"] for w in all_text_words
            if w["word"].lower() in self.EMOTION_WORDS_SET
        ]
        if len(emotion_words) < 5:
            emotion_words = sorted(self.EMOTION_WORDS_SET)

        # Извлекаем ngram-строки из словарей
        bigrams_clean: list[dict[str, Any]] = []
        for b in top_bigrams:
            if isinstance(b, dict) and "ngram" in b:
                bigrams_clean.append({"phrase": b["ngram"], "count": b["count"]})

        trigrams_clean: list[dict[str, Any]] = []
        for t in top_trigrams:
            if isinstance(t, dict) and "ngram" in t:
                trigrams_clean.append({"phrase": t["ngram"], "count": t["count"]})

        result: dict[str, Any] = {
            "generated_at": self._build_timestamp(),
            "top_words_in_titles": top_words_in_titles,
            "top_words_in_texts": top_words_in_texts,
            "power_bigrams": bigrams_clean,
            "power_trigrams": trigrams_clean,
            "finance_terms": finance_terms,
            "emotion_words": emotion_words,
        }

        self._save("vocabulary.json", result)
        self.logger.info("build_vocabulary: %.2f с", time.time() - start)
        return result

    # ── build_hooks ──────────────────────────────────────────────────

    @staticmethod
    def _classify_hook(first_sentence: str) -> str | None:
        """
        Классифицировать первое предложение по типу хука.

        Возвращает имя типа или None если не удалось классифицировать.
        """
        text = first_sentence.strip()

        if not text:
            return None

        # question — заканчивается на ?
        if text.endswith("?"):
            return "question"

        # time_marker — привязка ко времени
        time_pattern = re.compile(
            r"(с\s+\d|в\s+\d{4}|через\s+(год|месяц|неделю)|недавно|вчера|"
            r"в\s+(январе|феврале|марте|апреле|мае|июне|июле|августе|"
            r"сентябре|октябре|ноябре|декабре))",
            re.IGNORECASE,
        )
        if time_pattern.search(text):
            return "time_marker"

        # promise — обещание
        if re.search(r"\b(узнаете|расскажу|покажу|объясню|научу|делюсь)\b", text, re.IGNORECASE):
            return "promise"

        # shocking_fact — содержит цифру + факт
        if re.search(r"\d+", text) and re.search(
            r"(упал|вырос|достиг|снизился|поднялся|составил|превысил|"
            r"сократился|увеличился|выросли|упали)",
            text,
            re.IGNORECASE,
        ):
            return "shocking_fact"

        # personal_story — личная история
        if re.search(
            r"^(я\s|он\s|она\s|дед\s|бабушк|мать\s|отец\s|мой\s|моя\s|мои\s|"
            r"наша\s|наш\s|мы\s|они\s|муж\s|жен\s|сын\s|дочь\s|внук\s|"
            r"родител|сосед|подруг|друз)",
            text,
            re.IGNORECASE,
        ):
            return "personal_story"

        # problem — проблема
        if re.search(
            r"\b(проблем|ошибк|почему\s|нельзя|опасно|сложно|трудно|"
            r"худш|главн|сам\w+\s+ошибк)",
            text,
            re.IGNORECASE,
        ):
            return "problem"

        return None

    def build_hooks(self) -> dict[str, Any]:
        """
        Построить hooks.json из текстов статей в БД.

        Алгоритм:
        1. SELECT text FROM articles WHERE is_parsed=1
        2. Взять первые 300 символов каждого текста
        3. Найти первое предложение (до первой точки)
        4. Классифицировать по типу хука
        5. Сохранить топ-3 примера каждого типа
        """
        self.logger.info("=== build_hooks ===")
        start = time.time()

        # Загружаем тексты из БД
        texts: list[str] = []
        try:
            cursor = self.db_conn.cursor()
            cursor.execute(
                "SELECT text FROM articles WHERE is_parsed=1 AND text IS NOT NULL"
            )
            rows = cursor.fetchall()
            texts = [row["text"] for row in rows if row["text"] and row["text"].strip()]
            self.logger.info("Загружено %d текстов из БД", len(texts))
        except sqlite3.Error as e:
            self.logger.error("Ошибка загрузки текстов из БД: %s", e)

        # Классифицируем хуки
        hook_counts: dict[str, int] = {}
        hook_examples: dict[str, list[str]] = {}

        for text in texts:
            first_300 = text[:300]
            # Первое предложение: до первой точки
            dot_pos = first_300.find(".")
            first_sentence = first_300[: dot_pos + 1] if dot_pos > 0 else first_300

            hook_type = self._classify_hook(first_sentence)
            if hook_type is None:
                hook_type = "other"

            hook_counts[hook_type] = hook_counts.get(hook_type, 0) + 1
            if hook_type not in hook_examples:
                hook_examples[hook_type] = []
            if len(hook_examples[hook_type]) < 3:
                hook_examples[hook_type].append(first_sentence.strip())

        # Описания типов хуков
        HOOK_TYPE_INFO: dict[str, dict[str, str]] = {
            "shocking_fact": {
                "template": "{ПОКАЗАТЕЛЬ} {упал/вырос/достиг} {ЦИФРА}",
                "effectiveness": "Высокая для аналитических статей",
            },
            "personal_story": {
                "template": "{ГЕРОЙ} {ДЕЙСТВИЕ_В_ПРОШЛОМ}",
                "effectiveness": "Максимальная для vzoprodengi-стиля",
            },
            "question": {
                "template": "{КОНКРЕТНЫЙ_ВОПРОС}?",
                "effectiveness": "Средняя, работает для how-to формата",
            },
            "problem": {
                "template": "Почему {ПРОБЛЕМА} — {ОБЪЯСНЕНИЕ}",
                "effectiveness": "Высокая для образовательного контента",
            },
            "promise": {
                "template": "{Покажу/Расскажу/Научу} {ЧТО_КОНКРЕТНО}",
                "effectiveness": "Средняя, требует выполнения обещания",
            },
            "time_marker": {
                "template": "{ДАТА/СРОК} {СОБЫТИЕ}",
                "effectiveness": "Высокая для новостного контента",
            },
            "other": {
                "template": "{СВОБОДНЫЙ_ФОРМАТ}",
                "effectiveness": "Низкая — неклассифицированные хуки",
            },
        }

        # Собираем результат
        hook_types: dict[str, dict[str, Any]] = {}
        for htype, info in HOOK_TYPE_INFO.items():
            hook_types[htype] = {
                "count": hook_counts.get(htype, 0),
                "examples": hook_examples.get(htype, []),
                "template": info["template"],
                "effectiveness": info["effectiveness"],
            }

        # Лучшие хуки (короткие — до 120 символов, с наибольшим count в своём типе)
        all_examples: list[tuple[str, str]] = []
        for htype, ex_list in hook_examples.items():
            for ex in ex_list:
                if len(ex) <= 120:
                    all_examples.append((ex, htype))
        best_hooks = [ex for ex, _ in all_examples[:10]]

        result: dict[str, Any] = {
            "generated_at": self._build_timestamp(),
            "hook_types": hook_types,
            "best_hooks_overall": best_hooks,
        }

        self._save("hooks.json", result)
        self.logger.info("build_hooks: %.2f с", time.time() - start)
        return result

    # ── build_article_structure ──────────────────────────────────────

    def build_article_structure(self) -> dict[str, Any]:
        """
        Построить article_structure.json из статистики.

        Использует self.stats['text_length'] и self.stats['structure'].
        Для by_channel_style запрашивает средние по каждому каналу из БД.
        """
        self.logger.info("=== build_article_structure ===")
        start = time.time()

        text_length = self.stats.get("text_length", {})
        structure = self.stats.get("structure", {})
        titles = self.stats.get("titles", {})

        total_articles = text_length.get("total_articles", 0)
        mean_words = text_length.get("mean_words", 0)
        median_words = text_length.get("median_words", 0)

        paragraphs = structure.get("paragraphs", {})
        headers = structure.get("headers", {})
        images = structure.get("images", {})

        # by_channel из БД
        by_channel_style: dict[str, dict[str, Any]] = {}
        try:
            cursor = self.db_conn.cursor()
            cursor.execute(
                """
                SELECT c.slug,
                       AVG(a.word_count) as avg_words,
                       AVG(a.paragraphs_count) as avg_paragraphs
                FROM articles a
                JOIN channels c ON a.channel_id = c.id
                WHERE a.is_parsed=1
                GROUP BY c.slug
                """
            )
            for row in cursor.fetchall():
                slug = row["slug"]
                style_info = self.CHANNEL_STYLES.get(slug, {})
                by_channel_style[slug] = {
                    "style": style_info.get("style", "general"),
                    "avg_words": round(row["avg_words"], 1) if row["avg_words"] else 0,
                    "avg_paragraphs": round(row["avg_paragraphs"], 1) if row["avg_paragraphs"] else 0,
                    "typical_pattern": style_info.get("typical_pattern", "other"),
                    "description": style_info.get("description", ""),
                }
        except sqlite3.Error as e:
            self.logger.error("Ошибка загрузки by_channel из БД: %s", e)

        result: dict[str, Any] = {
            "generated_at": self._build_timestamp(),
            "corpus_size": total_articles,
            "recommended_length": {
                "min_words": 400,
                "max_words": 900,
                "optimal_words": round(median_words),
                "note": f"Медиана корпуса ({round(mean_words)} ср.). "
                        f"vzoprodengi длиннее (800-1200), igorfaynman короче (300-500).",
            },
            "recommended_structure": {
                "paragraphs_min": 8,
                "paragraphs_max": 25,
                "paragraphs_optimal": 14,
                "use_headers": True,
                "headers_count_optimal": 2,
                "headers_note": f"{headers.get('percent_with_headers', 57)}% статей используют подзаголовки h2/h3",
                "use_images": True,
                "images_count_optimal": 1,
                "images_note": f"{images.get('percent_with_images', 95)}% статей имеют обложку, "
                              f"{round(images.get('mean', 0), 1)} ср. изображений на статью",
            },
            "by_channel_style": by_channel_style,
            "paragraph_recommendations": {
                "opening": "1-2 абзаца, хук + контекст проблемы",
                "body": "8-15 абзацев, раскрытие темы с подзаголовками",
                "conclusion": "1-2 абзаца, вывод или призыв к действию",
            },
        }

        self._save("article_structure.json", result)
        self.logger.info("build_article_structure: %.2f с", time.time() - start)
        return result

    # ── build_topic_clusters ─────────────────────────────────────────

    def build_topic_clusters(self) -> dict[str, Any]:
        """
        Построить topic_clusters.json.

        Алгоритм:
        1. Загрузить все статьи: SELECT title, text FROM articles
        2. Для каждого кластера подсчитать сколько keywords встречается
           в (title + text).lower()
        3. Если >= 2 — статья попадает в кластер
        4. Для каждого кластера собрать топ-слова и примеры заголовков
        5. Подсчитать overlap
        """
        self.logger.info("=== build_topic_clusters ===")
        start = time.time()

        # Загружаем статьи
        articles: list[dict[str, str]] = []
        try:
            cursor = self.db_conn.cursor()
            cursor.execute(
                "SELECT title, text FROM articles WHERE is_parsed=1 AND text IS NOT NULL"
            )
            for row in cursor.fetchall():
                articles.append({
                    "title": row["title"] or "",
                    "text": row["text"] or "",
                })
            self.logger.info("Загружено %d статей для кластеризации", len(articles))
        except sqlite3.Error as e:
            self.logger.error("Ошибка загрузки статей: %s", e)

        # Кластеризация
        total = len(articles)
        cluster_articles: dict[str, list[dict[str, str]]] = {
            name: [] for name in self.CLUSTER_KEYWORDS
        }

        for article in articles:
            combined = (article["title"] + " " + article["text"]).lower()
            for cluster_name, keywords in self.CLUSTER_KEYWORDS.items():
                match_count = sum(1 for kw in keywords if kw in combined)
                if match_count >= 2:
                    cluster_articles[cluster_name].append(article)

        # Собираем результат по каждому кластеру
        clusters: dict[str, dict[str, Any]] = {}
        for cluster_name, arts in cluster_articles.items():
            art_count = len(arts)
            percentage = round(art_count / total * 100, 1) if total else 0

            # Собираем слова и их частоты
            word_counts: dict[str, int] = {}
            for art in arts:
                combined = (art["title"] + " " + art["text"]).lower()
                # Считаем только ключевые слова кластера и их вхождения
                for kw in self.CLUSTER_KEYWORDS[cluster_name]:
                    count = combined.count(kw)
                    if count > 0:
                        word_counts[kw] = word_counts.get(kw, 0) + count

            top_words = sorted(
                [{"word": w, "frequency": c} for w, c in word_counts.items()],
                key=lambda x: x["frequency"],
                reverse=True,
            )[:5]

            # Примеры заголовков
            example_titles = [a["title"] for a in arts[:3]]

            clusters[cluster_name] = {
                "article_count": art_count,
                "percentage": percentage,
                "top_words": top_words,
                "example_titles": example_titles,
            }

        # Overlap analysis
        article_cluster_counts: list[int] = []
        for article in articles:
            combined = (article["title"] + " " + article["text"]).lower()
            count = 0
            for cluster_name, keywords in self.CLUSTER_KEYWORDS.items():
                if sum(1 for kw in keywords if kw in combined) >= 2:
                    count += 1
            article_cluster_counts.append(count)

        avg_clusters = round(
            sum(article_cluster_counts) / len(article_cluster_counts), 1
        ) if article_cluster_counts else 0

        # Самые частые комбинации кластеров
        pair_counts: dict[tuple[str, ...], int] = {}
        for article in articles:
            combined = (article["title"] + " " + article["text"]).lower()
            matched = []
            for cluster_name, keywords in self.CLUSTER_KEYWORDS.items():
                if sum(1 for kw in keywords if kw in combined) >= 2:
                    matched.append(cluster_name)
            matched.sort()
            if len(matched) >= 2:
                for i in range(len(matched)):
                    for j in range(i + 1, len(matched)):
                        pair = (matched[i], matched[j])
                        pair_counts[pair] = pair_counts.get(pair, 0) + 1

        most_common_combinations = sorted(
            [{"clusters": list(k), "count": v} for k, v in pair_counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        )[:5]

        result: dict[str, Any] = {
            "generated_at": self._build_timestamp(),
            "total_articles": total,
            "clusters": clusters,
            "overlap_analysis": {
                "average_clusters_per_article": avg_clusters,
                "most_common_combinations": most_common_combinations,
            },
        }

        self._save("topic_clusters.json", result)
        self.logger.info("build_topic_clusters: %.2f с", time.time() - start)
        return result

    # ── build_all ────────────────────────────────────────────────────

    def build_all(self) -> dict[str, Any]:
        """
        Запустить все методы построения базы знаний.

        Порядок:
        1. build_title_patterns
        2. build_vocabulary
        3. build_hooks
        4. build_article_structure
        5. build_topic_clusters

        Создаёт meta.json и возвращает сводку.
        """
        self.logger.info("=" * 50)
        self.logger.info("ЗАПУСК ПОЛНОГО ПОСТРОЕНИЯ БАЗЫ ЗНАНИЙ")
        self.logger.info("=" * 50)

        overall_start = time.time()

        # Порядок важен: build_title_patterns → build_vocabulary → build_hooks
        # → build_article_structure → build_topic_clusters
        steps: list[tuple[str, str]] = [
            ("title_patterns", "build_title_patterns"),
            ("vocabulary", "build_vocabulary"),
            ("hooks", "build_hooks"),
            ("article_structure", "build_article_structure"),
            ("topic_clusters", "build_topic_clusters"),
        ]

        files_created: list[str] = []
        for file_name, method_name in steps:
            method = getattr(self, method_name, None)
            if method is None:
                self.logger.error("Метод %s не найден", method_name)
                continue
            try:
                method()
                files_created.append(file_name)
            except Exception as e:
                self.logger.exception("Ошибка в %s: %s", method_name, e)

        total_time = time.time() - overall_start

        # Сводка
        corpus = self.stats.get("corpus", {})
        summary: dict[str, Any] = {
            "generated_at": self._build_timestamp(),
            "files_created": files_created,
            "statistics_source": self.STATISTICS_PATH,
            "articles_analyzed": corpus.get("total_articles", 0),
            "corpus_channels": corpus.get("total_channels", 0),
            "build_time_seconds": round(total_time, 2),
        }

        # Сохраняем meta.json
        self._save("meta.json", summary)

        self.logger.info("=" * 50)
        self.logger.info(
            "Построение завершено за %.2f с. Создано файлов: %d",
            total_time,
            len(files_created),
        )
        self.logger.info("=" * 50)

        return summary

    # ── close ────────────────────────────────────────────────────────

    def close(self) -> None:
        """Закрыть соединение с БД."""
        try:
            self.db_conn.close()
            self.logger.info("Соединение с БД закрыто")
        except sqlite3.Error as e:
            self.logger.error("Ошибка закрытия БД: %s", e)