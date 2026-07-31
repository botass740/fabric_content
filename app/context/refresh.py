"""
Обновление weekly_hot.txt.

Два входа:
  - refresh_via_llm(settings) — просит LLM набросать 5-7 «правдоподобных» горячих тем
    в финансовой нише России. Возвращает список блоков (str). Ничего не пишет на диск.
  - apply_weekly_hot(settings, blocks) — записывает переданные блоки в weekly_hot.txt.

Развязка вход/запись сделана намеренно: Telegram-бот сначала показывает превью
админу, и только после подтверждения кнопкой применяет.
"""

from __future__ import annotations

import logging
import re
from datetime import date

from app.context.trends import write_weekly_hot
from app.generators.llm import get_llm_client
from app.generators.utils import parse_json_list


_REFRESH_PROMPT = """Ты — редактор Дзена в нише «деньги, финансовые ошибки, бытовая психология денег».

Задача: составь список из 5-7 горячих тем недели, которые сейчас на слуху у русскоязычной аудитории Дзена.
Ориентир: сегодня {today}.

Требования к каждому пункту:
- одна конкретная ситуация или новость, а не абстрактная «тема»;
- есть узнаваемая деталь: цифра, название сервиса, сезонная привязка, свежая новость;
- бытовой уровень (то, что обсуждают в очереди, чате родителей, курилке), а не макроэкономика;
- если сомневаешься в свежести — пиши то, что заведомо продолжает быть болью (ЖКХ, МФО, подписки, вклады, маркетплейсы, семейные конфликты о деньгах, налоги, отпуск).

Категории, из которых можно брать (не все одновременно, а 5-7 разных):
- ЖКХ и коммунальные квитанции
- МФО, кредиты, кредитки
- ЦБ, ставка, вклады, налоги на доход по вкладам
- Маркетплейсы (WB, Ozon, YM): цены, подделки, возвраты
- Подписки и автосписания
- Семейные конфликты о деньгах, бюджет, дети, родители
- Импульсные траты, доставка, кофе, «мелочи»
- Отпуск, сезонные траты (лето: путёвки, дача, ремонт)
- Устаревшие советы по экономии

Формат ответа: строго JSON-массив строк.
Каждая строка — 1-3 предложения (короткая формулировка + опциональное уточнение).
Никаких вступлений, никакого markdown, только JSON.

Пример хорошего ответа:
[
  "Новые квитанции за ЖКХ пришли в первые дни июля — жалобы в соцсетях на рост на 10-15%.",
  "WB и Ozon снова обсуждают подделки: техника Apple и БАДы, возврат работает через раз.",
  "Отпуск в Сочи: средний чек в кафе сравнялся с Турцией, люди пишут «второй раз не поедем»."
]
"""


def refresh_via_llm(settings, *, logger: logging.Logger | None = None) -> list[str]:
    """
    Возвращает список текстовых блоков — черновик горячих тем недели.
    Ничего не пишет в файл; вызывающая сторона решает, применять или нет.
    """
    log = logger or logging.getLogger(__name__)

    client = get_llm_client(settings, log)

    prompt = _REFRESH_PROMPT.format(today=date.today().isoformat())

    response = client.chat(
        system="Ты редактор Дзена. Возвращай только JSON-массив без пояснений и markdown.",
        user=prompt,
        temperature=0.8,
        max_tokens=4096,
    )

    blocks = parse_json_list(response)
    blocks = [b.strip() for b in blocks if b and b.strip()]
    log.info(f"refresh_via_llm produced {len(blocks)} blocks")
    return blocks


def apply_weekly_hot(
    settings,
    blocks: list[str],
    *,
    logger: logging.Logger | None = None,
) -> None:
    """
    Записывает переданные блоки в weekly_hot.txt.
    Добавляет служебную шапку с датой обновления.
    """
    header = (
        "Горячие темы недели (обновляется вручную командой /refresh_trends или /set_weekly).\n"
        f"Последнее обновление: {date.today().isoformat()}"
    )
    write_weekly_hot(settings, blocks, header=header, logger=logger)


def parse_raw_input(raw: str) -> list[str]:
    """
    Парсит текст, вставленный админом через /set_weekly.
    Разделители: двойной перенос строки или пронумерованные пункты (1., 2., ...).
    """
    text = raw.strip()
    if not text:
        return []

    # Убираем ведущую пронумерацию у строк
    lines = text.splitlines()
    cleaned: list[str] = []
    current: list[str] = []
    numbered = re.compile(r"^\s*\d+[\.\)]\s+")
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current:
                cleaned.append(" ".join(current).strip())
                current = []
            continue
        stripped = numbered.sub("", stripped)
        current.append(stripped)
    if current:
        cleaned.append(" ".join(current).strip())

    return [c for c in cleaned if c]
