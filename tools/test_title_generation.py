import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

import os
import sys

# Добавляем корень проекта в sys.path, чтобы был виден пакет app/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Отключаем системный прокси для httpx, как в main.py
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

from app.config.settings import get_settings
from app.generators.titles import generate_titles


def main():
    settings = get_settings()

    test_topic = "Ключевая ставка ЦБ снижена до 14%: что это значит для вкладов"

    print("Генерация заголовков с использованием базы знаний...")
    print(f"Тема: {test_topic}\n")

    # Тип хука и голос берём из матрицы (иначе generate_titles их требует)
    titles = generate_titles(
        settings,
        hook_type="цифра + контраст",
        hero="айтишник 35+",
        topic=test_topic,
        n=5,
    )

    print("Результат:")
    for i, title in enumerate(titles, 1):
        print(f"  {i}. {title}")


if __name__ == "__main__":
    main()
