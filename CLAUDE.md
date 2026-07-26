# Dzen Article Publisher

Автоматическая генерация и публикация статей в Яндекс Дзен через Telegram-бота.

**Текущий статус, инфраструктура (VPS, прокси, systemd) и известные грабли — в `dzen.md`. Читать его в начале работы обязательно.**

## Архитектура

```
main.py → Telegram bot (app/telegram/bot.py)
         → Database (app/database/db.py) — SQLite
         → Generators (app/generators/)
           → llm.py — абстракция LLM (LLM_PROVIDER: openrouter/anthropic)
           → topics.py — генерация тем
           → titles.py — генерация заголовков
           → article_plan.py — план статьи
           → articles.py — текст статьи
           → story_check.py — проверка сюжета на правдоподобие
           → images.py — обложка (FLUX / placeholder)
           → topic_matrix.py — матрица разнообразия (5 осей)
         → Publisher (app/publishers/dzen_publisher.py) — Playwright
```

Прод: VPS (Москва), systemd `dzen-bot.service` + `xvfb.service`. Из России Telegram и OpenRouter доступны **только через Cloudflare Workers-прокси** (`TELEGRAM_API_BASE_URL`, `OPENROUTER_BASE_URL` в `.env` на VPS) — не удалять, детали в `dzen.md`.

## Pipeline генерации статьи

1. `pick_combination(db)` — выбор редкой комбинации из 5 осей (hero, emotion, format, trigger, hook_type)
2. `generate_topics(settings, combination=..., recent_topics=...)` — темы в рамках комбинации
3. `generate_titles(settings, topic=..., hook_type=..., hero=...)` — заголовки под тип хука
4. `generate_article_plan(settings, topic=..., title=..., hero=..., emotion=..., format=...)` — структурированный JSON-план
5. `generate_article(settings, topic=..., title=..., plan=..., hero=..., emotion=..., format=...)` — текст статьи
6. `generate_cover(settings, topic=..., title=..., content=...)` — обложка (FLUX через OpenRouter → placeholder)
7. `db.register_combination(...)` — сохранить использованную комбинацию

## Матрица осей (topic_matrix.py)

- **hero**: 12 архетипов (мать в декрете, айтишник 35+, учительница 45+, ...)
- **emotion**: 12 эмоций (тихая злость, удивление, злорадство, ...)
- **format**: 8 форматов (исповедь, разбор истории, контр-мнение, ...)
- **trigger**: 15 денежных триггеров (подписки, МФО, маркетплейсы, ...)
- **hook_type**: 6 типов хука (цифра+контраст, вопрос-провокация, анти-совет, ...)

Выбор: взвешенный (редкие значения выше вес) + защита от точных повторов за 30 дней.

## База данных (SQLite)

Таблицы:
- `articles` — id, title, content, image_path, status, created_at, published_at
- `used_combinations` — hero, emotion, format, trigger, hook_type, topic, article_id, created_at
- `used_topics` — topic, created_at

Статусы: `generated` → `approved` → `published` | `rejected`

## Публикация в Дзен (Playwright)

1. Открыть dzen.ru → профиль → "Создать публикацию" → "Написать статью"
2. Вставить заголовок через Ctrl+V (pyperclip)
3. Загрузить обложку через `expect_file_chooser` + `set_files()`
4. Закрыть popup загрузки (Escape / клик вне)
5. Вставить контент через Ctrl+V (pyperclip), разделяя абзацы `\n\n`
6. Нажать "Опубликовать" дважды (первый клик открывает диалог)
7. Проверить URL: наличие `/a/` = успех

## Telegram Bot

Команды:
- `/start` — приветствие
- `/generate` — создаёт статью (полный цикл)
- `/queue` — очередь на публикацию
- `/list` — последние статьи
- `/stats` — статистика
- `/publish_last` — опубликовать последнюю одобренную
- `/login` — открыть браузер для входа в Дзен

Кнопки под превью: ✅ Опубликовать / 🔄 Перегенерировать / ❌ Удалить

### Автогенерация по расписанию (JobQueue)

- Слоты 09:00 / 14:00 / 19:00 МСК + случайная задержка 0–30 мин (`AUTOGEN_TIMES`, `AUTOGEN_MAX_DELAY_S` в `bot.py`).
- Режим подтверждения: бот присылает превью, публикует человек кнопкой. Автопубликации нет — так задумано.
- 21:00 МСК — сводка очереди неопубликованных.
- `asyncio.Lock` против наложения циклов; ошибки генерации нефатальны.

## Обложки (images.py)

- FLUX через OpenRouter (`black-forest-labs/flux.2-pro`)
- Пайплайн: анализ статьи → выбор шаблона → построение промта → FLUX → сохранение
- При ошибке FLUX — placeholder (PIL, серый фон с текстом)
- Временно отключается заменой `if settings.openrouter_api_key:` на `if False:` в `images.py:134`

## Заметки

- Все промты в `app/prompts/` — переписаны под качество: квоты на цифры/диалоги/бренды, запрет афоризмов
- `_cut_second_ending()` в `articles.py` — постпроцессор, режущий «второй финал»
- `tools/record_cover_upload.py` — диагностика Playwright-селекторов