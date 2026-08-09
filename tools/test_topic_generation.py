import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

import os
import sys

# Добавляем корень проекта в sys.path, чтобы был виден пакет app/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Отключаем системный прокси для httpx, как в main.py
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

# Windows-консоль по умолчанию cp1251 не умеет печатать ₽ — пишем как UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from app.config.settings import get_settings
from app.generators.topics import generate_topics

# Комбинация — пример из матрицы осей (generate_topics инжектит их в промт)
COMBINATION = {
    "hero": "айтишник 35+, живёт один в съёмной квартире",
    "emotion": "тихая злость на систему",
    "format": "исповедь от первого лица",
    "trigger": "подписки на сервисы",
    "hook_type": "цифра + контраст (конкретная сумма или срок в первой строке)",
}

# Минимальный форматированный блок актуальных триггеров (как в trends)
LIVE_TRIGGERS = (
    "Актуальный фон:\n"
    "- ЦБ снизил ключевую ставку до 14%\n"
    "- Сервисы подняли тарифы на подписки\n"
)


def main():
    settings = get_settings()

    print("Генерация тем с базой знаний...")
    print(f"Матрица: {COMBINATION}\n")

    topics = generate_topics(
        settings,
        combination=COMBINATION,
        live_triggers=LIVE_TRIGGERS,
        n=3,
    )

    print("Результат:")
    for i, topic in enumerate(topics, 1):
        print(f"  {i}. {topic}")


if __name__ == "__main__":
    main()
