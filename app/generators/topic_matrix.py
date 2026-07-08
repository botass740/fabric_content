"""
Матрица осей для генерации разнообразных тем.
Каждая тема статьи описывается комбинацией из 5 осей.
Цель — уйти от монотонных "мужчина купил статусную вещь и жалеет".
"""
import logging
import random
from collections import Counter


HERO_ARCHETYPES = [
    "мать в декрете с маленьким ребёнком",
    "айтишник 35+, живёт один в съёмной квартире",
    "учительница 45+ из небольшого города",
    "пенсионерка, помогает взрослому сыну деньгами",
    "разведённая женщина с ипотекой и двумя детьми",
    "студент на первой стажировке",
    "предприниматель после провала бизнеса",
    "муж, у которого жена ведёт семейный бюджет",
    "человек, вышедший из долговой ямы год назад",
    "мужчина 50+, работает вахтой",
    "молодая пара, только съехались",
    "фрилансер с нестабильным доходом",
]

EMOTIONS = [
    "тихая злость на систему",
    "удивление от собственного открытия",
    "злорадство над своими прошлыми привычками",
    "облегчение",
    "азарт",
    "ностальгия по временам, когда денег было меньше",
    "стыд",
    "надежда после долгой апатии",
    "зависть к близким",
    "гордость за мелкую победу",
    "усталость от постоянных подсчётов",
    "спокойное принятие",
]

FORMATS = [
    "исповедь от первого лица",
    "разбор чужой истории (соседка, коллега, родственник)",
    "контр-мнение против расхожего финансового совета",
    "разоблачение бытовой схемы (как нас разводят)",
    "список наблюдений от первого лица",
    "письмо себе прошлому (год/пять лет назад)",
    "дневник трат за неделю с выводами",
    "разговор с другом за чашкой чая",
]

MONEY_TRIGGERS = [
    "подписки на сервисы",
    "МФО и микрозаймы",
    "маркетплейсы (Wildberries, Ozon)",
    "коммуналка и ЖКХ",
    "траты на детей",
    "подарки на праздники",
    "отпуск и путешествия",
    "ремонт квартиры",
    "доставка еды",
    "родственники просят в долг",
    "инфобизнес и онлайн-курсы",
    "автомобиль (бензин, ремонт, страховка)",
    "здоровье и лекарства",
    "продукты в супермаркете",
    "школьные сборы и репетиторы",
]

HOOK_TYPES = [
    "цифра + контраст (конкретная сумма или срок в первой строке)",
    "вопрос-провокация (риторический вопрос, на который у читателя есть свой ответ)",
    "анти-совет (совет наоборот, ломающий шаблон)",
    "признание (сразу выкладываешь что-то стыдное или неудобное)",
    "правда о... (обещание раскрыть изнанку известного явления)",
    "неожиданное наблюдение (мелкая деталь, которая переворачивает представление)",
]


AXES = {
    "hero": HERO_ARCHETYPES,
    "emotion": EMOTIONS,
    "format": FORMATS,
    "trigger": MONEY_TRIGGERS,
    "hook_type": HOOK_TYPES,
}


def _pick_axis_value(values: list[str], recent: list[str]) -> str:
    """
    Взвешенный выбор значения оси: чем реже использовалось за окно,
    тем выше вес. Не использовавшиеся вовсе получают максимальный приоритет.
    """
    counts = Counter(recent)
    max_count = max(counts.values()) if counts else 0
    weights = [max_count - counts.get(v, 0) + 1 for v in values]
    return random.choices(values, weights=weights, k=1)[0]


def pick_combination(
    db,
    *,
    window_days: int = 30,
    max_attempts: int = 40,
    logger: logging.Logger | None = None,
) -> dict:
    """
    Выбирает комбинацию осей.
    Взвешенно предпочитает редкие значения и избегает точных повторов
    комбинаций за последние N дней.
    """
    logger = logger or logging.getLogger(__name__)
    recent = db.recent_combinations(days=window_days)

    recent_by_axis = {
        axis: [row[axis] for row in recent] for axis in AXES
    }
    recent_tuples = {
        (row["hero"], row["emotion"], row["format"], row["trigger"], row["hook_type"])
        for row in recent
    }

    for attempt in range(max_attempts):
        combination = {
            axis: _pick_axis_value(values, recent_by_axis[axis])
            for axis, values in AXES.items()
        }
        key = (
            combination["hero"],
            combination["emotion"],
            combination["format"],
            combination["trigger"],
            combination["hook_type"],
        )
        if key not in recent_tuples:
            logger.info(
                f"Picked combination (attempt {attempt + 1}): {combination}"
            )
            return combination

    logger.warning(
        f"Could not find unused combination after {max_attempts} attempts, returning last candidate"
    )
    return combination


def format_recent_topics(topics: list[str], limit: int = 30) -> str:
    """Форматирует список недавних тем для подстановки в промт."""
    if not topics:
        return "(пока пусто)"
    trimmed = topics[:limit]
    return "\n".join(f"- {t}" for t in trimmed)
