# tools/test_full_generation.py
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# Добавить путь к app/
sys.path.insert(0, str(Path(__file__).parent.parent))

# Windows-консоль по умолчанию cp1251 не умеет печатать ₽ — пишем как UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from app.config.settings import get_settings
from app.database.db import Database
from app.generators.topics import generate_topics
from app.generators.titles import generate_titles
from app.generators.article_plan import generate_article_plan
from app.generators.articles import generate_article
from app.generators.topic_matrix import pick_combination

# Единый блок актуальных триггеров для всех этапов — иначе тема/план/статья разъедутся
LIVE_TRIGGERS = (
    "Актуальный фон:\n"
    "- ЦБ снизил ключевую ставку до 14%\n"
    "- Сервисы подняли тарифы на подписки\n"
)


def main():
    print("=" * 60)
    print("ПОЛНАЯ ГЕНЕРАЦИЯ С БАЗОЙ ЗНАНИЙ")
    print("=" * 60)
    print()

    settings = get_settings()
    db = Database(settings.sqlite_db_path)
    combination = pick_combination(db)

    print(f"Матрица: {combination['hero']}; {combination['emotion']}; {combination['format']}")
    print(f"         триггер: {combination['trigger']}; хук: {combination['hook_type']}")
    print()

    # 1. Генерация тем (синхронная)
    print("1️⃣ Генерация тем...")
    topics = generate_topics(
        settings,
        combination=combination,
        live_triggers=LIVE_TRIGGERS,
        n=3,
    )
    topic = topics[0]
    print(f"   ✅ Тема: {topic}\n")

    # 2. Генерация заголовков (синхронная)
    print("2️⃣ Генерация заголовков...")
    titles = generate_titles(
        settings,
        topic=topic,
        hook_type=combination["hook_type"],
        hero=combination["hero"],
        n=5,
    )
    title = titles[0]
    print(f"   ✅ Заголовок: {title}\n")

    # 3. Генерация плана (синхронная, возвращает кортеж (text, json))
    print("3️⃣ Генерация плана...")
    plan_text, plan_json = generate_article_plan(
        settings,
        topic=topic,
        title=title,
        hero=combination["hero"],
        emotion=combination["emotion"],
        format=combination["format"],
        live_triggers=LIVE_TRIGGERS,
    )
    print(f"   ✅ План создан ({len(plan_text)} символов)\n")

    # 4. Генерация статьи (синхронная)
    print("4️⃣ Генерация статьи...")
    article = generate_article(
        settings,
        topic=topic,
        title=title,
        plan=plan_text,
        hero=combination["hero"],
        emotion=combination["emotion"],
        format=combination["format"],
        live_triggers=LIVE_TRIGGERS,
    )
    print(f"   ✅ Статья готова ({len(article)} символов)\n")

    # Результат
    print("=" * 60)
    print("РЕЗУЛЬТАТ")
    print("=" * 60)
    print(f"\nТЕМА:\n{topic}")
    print(f"\nЗАГОЛОВОК:\n{title}")
    print(f"\nПЕРВЫЕ 500 СИМВОЛОВ:\n{article[:500]}...")
    print(f"\nОБЩИЙ ОБЪЁМ: {len(article)} символов, ~{len(article.split())} слов")

    # Сохранить для просмотра
    with open("data/test_article_full.txt", "w", encoding="utf-8") as f:
        f.write(f"ТЕМА: {topic}\n\n")
        f.write(f"ЗАГОЛОВОК: {title}\n\n")
        f.write(f"СТАТЬЯ:\n{article}")

    print(f"\nПолная статья сохранена: data/test_article_full.txt")


if __name__ == "__main__":
    main()