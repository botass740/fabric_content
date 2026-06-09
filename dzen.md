# Карта проекта Dzen_2

**Назначение:** AI-автоматизация создания контента для Яндекс.Дзен в нише «финансы, заработок, бытовая психология денег». Проект на стадии активной разработки.

## Структура проекта

```
F:\Zerocoder\Dzen_2\
├── main.py                         # Точка входа: инициализация БД, логгера, каталогов + DEV-режим теста генерации
├── requirements.txt                # python-dotenv, python-telegram-bot, requests, openai, playwright, Pillow
├── .env / .env.example             # Конфигурационные переменные
├── model.txt                       # Конфиги для Continue (разные модели через OpenRouter)
│
├── app/
│   ├── config/
│   │   ├── settings.py             # Dataclass Settings (singleton) — все параметры из .env
│   │   └── logging.py              # Настройка логгера (файл + консоль)
│   │
│   ├── database/
│   │   └── db.py                   # SQLite ORM: таблица articles, CRUD + статусы
│   │
│   ├── generators/
│   │   ├── openrouter_client.py    # OpenRouter API клиент (через openai SDK)
│   │   ├── topics.py               # Генерация тем статей (JSON-массив)
│   │   ├── titles.py               # Генерация заголовков по теме
│   │   ├── articles.py             # Генерация полной статьи (с авто-продолжением если короткая)
│   │   ├── images.py               # ПУСТОЙ — заглушка для генерации изображений
│   │   └── utils.py                # load_prompt(), parse_json_list() с fallback-парсингом
│   │
│   ├── prompts/
│   │   ├── topic_prompt.txt        # Промт для генерации тем (ниша: финансы/психология денег)
│   │   ├── title_prompt.txt        # Промт для генерации заголовков (curiosity gap, без кликбейта)
│   │   └── article_prompt.txt      # Промт для статьи (4000-7000 симв., бытовой блог-стиль)
│   │
│   ├── publishers/
│   │   └── dzen_publisher.py       # ПУСТОЙ — заглушка для публикации в Дзен
│   │
│   └── telegram/
│       └── bot.py                  # ПУСТОЙ — заглушка для Telegram-бота
│
├── data/
│   ├── app.sqlite3                 # База данных SQLite
│   ├── articles/                   # Каталог для сохранённых статей
│   ├── images/                     # Каталог для сгенерированных изображений
│   └── logs/
│       └── app.log                 # Логи приложения
│
├── playwright_profile/             # Профиль Playwright для браузерной автоматизации
│
├── check_db.py                     # Утилита: проверка таблиц в БД
├── check_tables.py                 # Утилита: проверка таблиц в БД (дубль)
├── test_db_init.py                 # Утилита: инициализация БД
│
├── .continue/                      # Конфигурация Continue (AI-ассистент в IDE)
│
└── free-claude-code/               # Сторонний проект (free-claude-code) — клонированный репозиторий
```

## Ядро системы (реализовано)

| Модуль | Статус | Описание |
|--------|--------|----------|
| `config/settings.py` | Готов | Конфигурация через .env + dataclass с computed-полями |
| `config/logging.py` | Готов | Двухканальный логгер (DEBUG в файл + DEBUG в консоль) |
| `database/db.py` | Готов | SQLite с таблицей `articles`, 4 статуса, индексы, CRUD |
| `generators/openrouter_client.py` | Готов | OpenAI-совместимый клиент для OpenRouter API |
| `generators/topics.py` | Готов | Генерация N тем через AI → JSON-парсинг |
| `generators/titles.py` | Готов | Генерация N заголовков по теме → JSON-парсинг |
| `generators/articles.py` | Готов | Генерация статьи 4000-7000 символов, с авто-продолжением |
| `generators/utils.py` | Готов | Загрузка промтов + 3-уровневый парсер JSON/списков |
| `prompts/*.txt` | Готов | 3 промта (темы, заголовки, статьи) на русском |
| `main.py` | Готов | Точка входа: инициализация + DEV-режим (DEV_RUN_GENERATION=1) |

## Заглушки (не реализовано)

| Модуль | Статус | Предполагаемое назначение |
|--------|--------|---------------------------|
| `generators/images.py` | Пустой | Генерация изображений через OpenAI (gpt-image-1) |
| `publishers/dzen_publisher.py` | Пустой | Автопостинг в Дзен через Playwright |
| `telegram/bot.py` | Пустой | Telegram-бот для управления контентом |

## Бизнес-логика

**Конвейер генерации контента:**
1. `generate_topics(n)` → AI генерирует список тем
2. `generate_titles(topic, n)` → AI генерирует заголовки под тему
3. `generate_article(topic, title)` → AI пишет статью (с авто-дополнением если <3500 симв.)
4. `generate_images()` — не реализовано

**Статусы статей (workflow):**
`generated` → `approved` → `published` / `rejected`

**Модель AI по умолчанию:** `deepseek/deepseek-chat` через OpenRouter API

## Технический стек
- Python 3.11
- OpenAI SDK (для OpenRouter API)
- SQLite (без ORM, прямой sqlite3)
- Playwright (для будущей браузерной автоматизации Дзена)
- python-telegram-bot (для будущего Telegram-бота)
- Pillow (для работы с изображениями)

## Ключевые архитектурные решения
- **Singleton** для `Settings` (глобальная переменная `_settings`)
- **Dataclass** с `@property` для производных путей
- **Prompt-driven** архитектура: все промты в отдельных `.txt` файлах
- **OpenAI SDK** используется как универсальный клиент (работает и с OpenRouter, и с OpenAI Images)
- **3-уровневый fallback** парсинг JSON-ответов от AI (прямой JSON → извлечение из строки → разбор по строкам)