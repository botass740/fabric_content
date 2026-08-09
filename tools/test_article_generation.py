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
from app.generators.articles import generate_article


TOPIC = "Почему я отменил все подписки после одного счёта"
TITLE = "2 490 ₽ за месяц: как я за ночь отменил все подписки и остался с одним только банком"
HERO = "айтишник 35+, живёт один в съёмной квартире"
EMOTION = "тихая злость на систему"
FORMAT = "исповедь от первого лица"

# Минимальный редакторский план той формы, что приходит из article_plan.py
PLAN = """central_conflict: герой обнаруживает, что платит за 7 подписок, о которых забыл
reader_question: сколько денег реально утекает на подписки и как понять, что пора их отменить
opening_scene: герой смотрит выписку из банка и видит автоплатежи на сервисы, которыми не пользуется
turning_point: герой решает отменить всё за один вечер и сталкивается с закрытыми кабинетами отмены
ending_goal: герой возвращает часть денег и оставляет одну подписку, которой реально пользуется
final_image: герой открывает приложение банка и видит пустой список автоплатежей"""

LIVE_TRIGGERS = (
    "Актуальный фон:\n"
    "- Сервисы подняли тарифы на подписки\n"
    "- ЦБ снизил ключевую ставку до 14%\n"
)


def main():
    settings = get_settings()

    print("Генерация статьи с базой знаний...")
    print(f"Тема: {TOPIC}\n")

    text = generate_article(
        settings,
        topic=TOPIC,
        title=TITLE,
        plan=PLAN,
        hero=HERO,
        emotion=EMOTION,
        format=FORMAT,
        live_triggers=LIVE_TRIGGERS,
    )

    print(f"Длина: {len(text)} знаков")
    print("\nНачало статьи:")
    print(text[:600])
    print("\n...\n")
    print("Конец статьи:")
    print(text[-400:])


if __name__ == "__main__":
    main()
