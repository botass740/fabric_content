# Dzen_2 — состояние проекта

**Обновлено:** 2026-08-09

**Назначение:** автогенерация и публикация статей в Яндекс.Дзен (ниша «финансы, заработок, бытовая психология денег»). Управление через Telegram-бота. Локальная разработка на Windows (`F:\Zerocoder\Dzen_2`), боевой запуск — на VPS.

Архитектура и пайплайн описаны в `CLAUDE.md` — здесь только то, чего там нет: текущий статус, инфраструктура, что сделано и что осталось.

---

## Главный контекст: мы в России

Это определяет почти все технические решения. Прямых подключений к внешним API с российского VPS нет — всё идёт через прокси.

| Сервис | Как подключаемся | Важно |
|--------|------------------|-------|
| Telegram Bot API | **Squid HTTP proxy на Хельсинки VPS → SSH-туннель (autossh)** — тот же путь, что OpenRouter | С 2026-08-09. Cloudflare Worker `telegram-api-proxy.botass740.workers.dev` **больше НЕ используется** (закомментирован в `.env`, бэкап `.env.cf-backup`): воркер резал загрузки файлов >~2 КБ, из-за этого фото-превью статей (107-158 КБ) никогда не доходило. Worker остаётся запасным вариантом — вернуть = раскомментировать `TELEGRAM_API_BASE_URL` в `.env` |
| OpenRouter (LLM + FLUX) | Squid HTTP proxy на Хельсинки VPS → SSH-туннель (autossh) | Cloudflare Workers (и Vercel) заблокированы OpenRouter по гео. Squid на `89.125.113.2:19502` через SSH-туннель с Московского VPS (localhost:3128). |

**Прокси-цепочки (обе от Московского VPS):**
- **OpenRouter / Telegram:** Moscow VPS → autossh SSH tunnel (port 19502) → Helsinki VPS → Squid (127.0.0.1:3128) → internet / api.telegram.org
- Telegram сейчас идёт **напрямую в api.telegram.org** через `HTTPS_PROXY=http://127.0.0.1:3128` (`TELEGRAM_API_BASE_URL` пустой) — multipart-файлы до 100+ КБ проходят за ~1s.

Адреса прокси подставляются через `.env`: `HTTP_PROXY`/`HTTPS_PROXY` (Squid-туннель), `OPENROUTER_BASE_URL`; `TELEGRAM_API_BASE_URL` закомментирован (воркер на случай отката).

**Секреты:** в `.env` лежат API-ключи и токен бота. В логах, которые присылает пользователь, токен бота виден внутри URL прокси — никогда не повторять его в ответах.

---

## Что сделано (готово и работает)

### Генерация
- Полный пайплайн работает: матрица осей → темы → заголовки → план → статья → проверка → обложка.
- Абстракция LLM-клиента (`llm.py`) — можно переключать провайдера через `LLM_PROVIDER` (`openrouter_client.py` / `anthropic_client.py`).
- Этап проверки сюжета `story_check.py` + `story_check_prompt.txt`.
- Обложки: FLUX через OpenRouter. `flux_client.py` принимает `base_url` (был захардкожен `openrouter.ai` — исправлено, теперь тоже через прокси). Fallback на PIL-placeholder при сбое.
- Промты переписаны под качество: квоты на цифры/диалоги/бренды, запрет афоризмов, постпроцессор `_cut_second_ending()`.

### Устойчивость доставки в Telegram
Ранняя проблема была в том, что статья и обложка генерировались нормально, но превью не доходило до Telegram — бесплатный прокси-воркер рвал соединение на больших загрузках. Сначала добавили ретраи/сжатие (ниже), но это не лечило корень.

**2026-08-09 — корень найден и убран:** воркер-прокси (`telegram-api-proxy.botass740.workers.dev`) вообще не пропускает multipart-аплоады крупнее пары КБ (измерено с VPS: 29 КБ уже висло, ответа нет даже за 180 s; sendMessage-JSON при этом проходил). Наши сжатые превью (107-158 КБ) валились всегда. Решение: **перевели Telegram на тот же Squid-туннель Хельсинки, что и OpenRouter** (`HTTPS_PROXY` env → api.telegram.org напрямую). Проверено вживую: фото 121 КБ (реальное превью статьи #34) ушло за секунды; `getMe`/`getUpdates` (лонг-поллинг) работают. Cloudflare Worker закомментирован в `.env` (бэкап `.env.cf-backup`).

Оставшиеся защитные меры в `app/telegram/bot.py`:
- Таймауты в **обеих** ветках `ApplicationBuilder`: `connect/read 30s`, `write 60s`, `pool 30s`.
- `_retry_send(coro_factory, what=, attempts=4)` — ретраи с backoff на `NetworkError`/`TimedOut`, уважает `RetryAfter`.
- `_compress_for_preview(image_path, max_side=1280, quality=82)` — PIL, PNG 1.6 МБ → JPEG ~100-160 КБ.
- Доставка превью нефатальна: если превью не ушло, но статья создана — сообщение «Статья готова (ID: N) … Открой её через /list или /queue».

**Важный нюанс про две картинки:** сжатие применяется **только к превью в Telegram**. В Дзен через `file_chooser.set_files()` уходит оригинальный файл (`dzen_publisher.py:303`) — качество обложки не страдает.

### Вход в Дзен — сделано на VPS
Профиль Chromium **нельзя** просто скопировать Windows → Linux: куки шифруются ключом ОС (DPAPI), на Linux не расшифруются. Поэтому переносим `storage_state` — кроссплатформенный JSON с куками и localStorage.

- `tools/dzen_login_local.py` — отработал локально: сохранил `dzen_state.json` (81 кука, 3 origin).
- `dzen_state.json` перенесён на VPS (`chmod 600`, в git не коммитится).
- `tools/dzen_load_state.py` — **отработал на VPS**: `Залито куки: 81 → Куки в профиле: 81 | yandex: 35 → ВХОД ПОДХВАЧЕН`. Заливает куки через `add_cookies()` + localStorage через `page.evaluate` (важно: `launch_persistent_context()` не принимает `storage_state`, только `new_context`).

Оба скрипта сами добавляют корень проекта в `sys.path` — запускать из корня.

### VPS развёрнут и бот работает

Сервер: `botas@132.243.214.3 -p 41480`, Ubuntu 24.04.4, Python 3.12.3, Москва (Citytelecom). Проект в `/home/botas/dzen-bot`.

Что настроено:
- venv + зависимости + Playwright Chromium (`playwright install-deps chromium` под sudo, затем `install chromium`).
- Swap 2 ГБ (RAM всего 1970 МБ, Chromium ест 500–800 МБ) — прописан в `/etc/fstab`.
- `xclip`, `xvfb` установлены; буфер обмена под Xvfb проверен — `pyperclip` копирует/читает кириллицу.
- **Два systemd-юнита:**
  - `xvfb.service` — `Xvfb :99 -screen 0 1600x1000x24`, `Restart=always`.
  - `dzen-bot.service` — `Requires=xvfb.service`, `Environment=DISPLAY=:99`, `RUN_BOT=1`, `Restart=on-failure`. Оба `enabled` (стартуют после ребута).
- Логи: `sudo journalctl -u dzen-bot -f`.

Проверено вживую с VPS: Telegram напрямую недоступен (`curl` → `000`), OpenRouter напрямую → `403`. **Оба воркера отдают `200`** — прокси реально обязательны, это не перестраховка. В `.env` на VPS дописаны `TELEGRAM_API_BASE_URL` и `OPENROUTER_BASE_URL` (в локальном `.env` их нет — локально прокси не нужен). Бэкап `.env.bak` рядом.

Бот в логе: `Using Cloudflare proxy: ... → getMe 200 → Application started`. LLM-вызов через прокси проверен отдельно — отвечает.

### Первая публикация с VPS — успешна (2026-07-26)

Полный цикл проверен вживую: `/generate` → превью в Telegram → «Опубликовать» → статья вышла в Дзен. Система работает end-to-end.

Первая попытка (2026-07-25) упала с «Expected 2 fields, got 0» — редактор Дзена открывается в **новой вкладке**, а его JS-бандл на слабом VPS грузится десятки секунд; старый код ждал ~5 секунд и искал поля в исходной вкладке (скриншот был полностью белым). Фикс: `_wait_for_editor_page()` в `dzen_publisher.py` — до 60 секунд опрашивает все вкладки контекста, ждёт появления ≥2 полей DraftEditor.

### Автогенерация по расписанию — работает в проде (2026-07-26)

Реализовано в `app/telegram/bot.py` через JobQueue (`python-telegram-bot[job-queue]`):

- **Слоты:** 09:00, 14:00, 19:00 МСК (`AUTOGEN_TIMES`, `run_daily` с `tzinfo=ZoneInfo("Europe/Moscow")` — VPS живёт в UTC, конвертация автоматическая).
- **Случайная задержка 0–30 мин** после каждого слота (`AUTOGEN_MAX_DELAY_S`), чтобы статьи не выходили секунда в секунду. Т.е. превью приходит, например, между 19:00 и 19:30 — это норма, не сбой.
- **Режим подтверждения:** бот только генерирует и присылает превью с кнопками; публикует человек кнопкой «✅ Опубликовать». Автопубликации нет — так и задумано.
- `asyncio.Lock` (`autogen_lock`) — защита от наложения циклов; если предыдущий ещё идёт, слот пропускается с warning в логе.
- **21:00 МСК** — сводка очереди (`queue_summary_job`): список неопубликованных статей; если очередь пуста — молчит.
- Ошибки генерации нефатальны: если статья создана, но превью не дошло — придёт сообщение с ID и подсказкой `/list`.

Проверено вживую: слот 14:00 → превью в 14:30 → публикация успешна. Во время публикации CPU (2 ядра) подскакивает до 95%, RAM 750–800 МБ — это нормально, Chromium. Пользователь подтвердил: **расписание менять не нужно, оставить как есть.**

---

## Что осталось сделать

Активных блокеров нет. Рабочий режим: следить за памятью при публикациях (1970 МБ + 2 ГБ swap); если бот умер во время публикации — `dmesg | grep -i oom`.

### Отложенная задача: исследование каналов Дзена (база знаний)

Начата, приостановлена на этапе планирования (2026-07-26). Суть: собрать базу знаний для генератора статей — **10 крупных + 15 средних + 15 небольших** финансовых каналов Дзена (личные финансы, семейный бюджет, заработок, финансовые ошибки, экономия, мошенничество, психология денег; авто-тематику НЕ трогать). По каждому каналу — метаданные + последние **50 публикаций** (URL, заголовок, дата, первые 500 символов, полный текст если возможно, просмотры/лайки/комментарии; отсутствующие значения оставлять пустыми, не выдумывать). Обложки — без компьютерного зрения, только простые признаки. Хранение — **отдельный SQLite**, перезапускаемый без изменения структуры. На этом этапе только сбор, **никакого анализа**.

Что уже выяснено (2026-07-27, `tools/dzen_explorer.py` + `tools/dzen_auth_explorer.py`):
- **Без куков ничего не работает**: dzen.ru отдаёт 302 на sso.passport.yandex.ru; RSS/sitemap/публичные API — тоже мимо.
- **requests + куки из `dzen_state.json` — работает полностью, браузер для сбора не нужен:**
  - Страница канала `dzen.ru/<slug>` → HTTP 200, внутри `<script type="application/ld+json">` — ItemList с 20 публикациями (name, image, description, url).
  - **Пагинация**: в HTML канала есть `"more":{"link":"https://dzen.ru/api/web/v1/channel-more?...&next_page_id=..."}` — GET по этой ссылке (с теми же куками) отдаёт JSON: `items[]` с title, text (сниппет), link, **views**, publicationDate (unix), timeToReadSeconds + следующий `more.link`. Цеплять цепочкой до конца (у tbank лента кончилась на ~33 статьях).
  - Страница статьи `dzen.ru/a/<id>` → HTTP 200, внутри `var _params=({"ssrData":...})` (искать `"ssrData"` и вырезать сбалансированный `{...}`): полный текст в `publishersResponse.data.data.publication.content.articleContent.contentState` (строка с draft-js JSON, блоки → текст), просмотры в `publication.publicationStatistics` (views, viewsTillEnd, pageViews), лайки/комменты в `socialMetaResponse.items[0].metaInfo` (likeCount, commentsCount), дата в `og.publishDate`. Проверено на живой статье: заголовок+дата+16291 просмотр+40 лайков+полный текст 2673 символа.
- Гаданные API (`launcher/feed`, `publisher/channel/articles`) — `{'error': 1, 'errtext': 'Unknown api request'}`, не тратить время.
- **Seed-список `tools/dzen_channels_seed.txt` наполовину мёртвый**: tinkoffjournal, sravni, rbc, banki-ru → 404; живые: tbank, fincult, tjournal. Перед сбором обязательна проверка существования (HTTP 200 и не SSO).
- Предупреждение: VK-автологин в куках отдаёт `invalid user` — на вход не влияет, но куки стареют; при массовых 302 на SSO — перелогин `tools/dzen_login_local.py`.

Открытые вопросы к пользователю: где запускать сбор (рекомендация — локально на Windows, чтобы не светить IP VPS с публикующим аккаунтом), пороги подписчиков для крупный/средний/небольшой, что делать с признаками обложек без CV.

---

## Хельсинки VPS — Squid прокси для OpenRouter

**Сервер:** `root@89.125.113.2 -p 19502` (пароль в .env.local), Ubuntu 22.04, 1GB RAM, 1 vCPU. Хельсинки.
**Назначение:** HTTP-прокси для обхода geo-блокировки OpenRouter (Россия, Cloudflare — заблокированы).

**Как работает:**
1. Squid (`/etc/squid/squid.conf`) слушает `127.0.0.1:3128` — только localhost, внешний доступ закрыт провайдером
2. На Московском VPS запущен `autossh-tunnel.service` — SSH-туннель через порт 19502: `localhost:3128 → Helsinki:127.0.0.1:3128`
3. Systemd-сервис `autossh-tunnel.service` на Московском VPS с `Restart=always`, `RestartSec=10`
4. В `.env` на Московском VPS: `OPENROUTER_BASE_URL=https://openrouter.ai/api/v1` + `HTTP_PROXY=http://127.0.0.1:3128`
5. SSH-ключ Московского VPS добавлен в `~/.ssh/authorized_keys` на Хельсинки (ed25519)

**Провайдер** блокирует все порты, кроме 19502 (SSH). Новые порты не открыть — только через SSH-туннели.

**Проверка:**
```bash
# На Московском VPS проверить туннель
systemctl status autossh-tunnel.service
# Тест OpenRouter
curl -x http://127.0.0.1:3128 https://openrouter.ai/api/v1/models
# Логи Squid на Хельсинки
tail -f /var/log/squid/access.log
```

## Известные грабли (проверено на практике)

- **Dzen анти-бот капча при публикации (2026-08-17).** Финальный API `editor-api/v2/update-publication-content-and-publish` может вернуть `400 {"errors":[{"type":"captcha-required-error"}]}`. Триггер — всплеск автоматизированных действий (диагностические Playwright-сессии, повторные публикации) с одного IP/аккаунта. Код распознаёт это (поле `captcha_hit`) и сообщает «нужна капча». Лечится паузой в несколько часов без автоматизации или ручной публикацией из обычного браузера владельца. Диагностику через Playwright на боевом аккаунте делать дозированно.
- **Публикация в Дзен переехала в новую студию (2026-08-17).** Старый путь «главная → аватар → Создать публикацию → Написать статью» умер: dzen перевёл создание в `/profile/editor/new/...` (Quill-редактор). Новый флоу в `dzen_publisher.py`: студия публикаций → кнопка `[class*='publications-layout__button-NT']` → меню «Написать статью» → редактор. Селекторы: заголовок `div[contenteditable][data-placeholder='Заголовок']`, контент `div.ql-editor[contenteditable]`, обложка — прямой `input[type=file]` (`set_input_files`), публикация — `[data-testid='article-publish-btn']`. Редактор грузится в той же вкладке до ~60с (поллим `ql-editor`, `_wait_for_editor()`).
- `launch_persistent_context()` **не принимает** `storage_state`. Только `new_context`. Для persistent-профиля — `add_cookies()` + localStorage через `evaluate`.
- `launch_persistent_context()` **не принимает** `storage_state`. Только `new_context`. Для persistent-профиля — `add_cookies()` + localStorage через `evaluate`.
- Профиль Chromium не переносится между Windows и Linux (шифрование куков ключом ОС).
- `OpenRouterClient.chat()` принимает **только keyword-аргументы**: `chat(system=..., user=..., max_tokens=...)`. Позиционный список сообщений не пройдёт.
- У `gpt-5` reasoning-токены съедают `max_tokens`. При `max_tokens=50` ответ пришёл **пустой** с `finish_reason=length` и `reasoning_tokens=99` — это не сбой прокси. Для проверок связи брать `max_tokens` от 800.
- Скрипты в `tools/` не видят `app/`, если не добавить корень в `sys.path` — уже добавлено в оба dzen-скрипта.
- Bash-инструмент иногда работает не из корня проекта: при `scp`/`py_compile` ставить `cd /f/Zerocoder/Dzen_2 && ...`.
- В PowerShell префикс `!` не работает — это префикс промта Claude Code, не оболочки.
- Низкая загрузка CPU/RAM — норма: бот I/O-bound, почти всё время ждёт сеть.
- Отключить FLUX временно: в `images.py:134` заменить `if settings.openrouter_api_key:` на `if False:`.

### История: мёртвый VPS 171.22.180.27 (закрыто, не возвращаться)

Промежуточный сервер, на который так и не удалось зайти (`Connection closed by ... port 22`). Съехали на 132.243.214.3. Диагноз для памяти: TCP-рукопожатие проходило (`debug1: Connection established`), обрыв на `kex_exchange_identification`, при этом заведомо закрытые порты (9, 34567, 51234) отвечали «открыто» → перед сервером стоял SYN-прокси / анти-DDoS фильтр провайдера. **Две гипотезы были опровергнуты:** «дело в ключах» (обрыв до аутентификации — ключ не при чём) и «провайдер режет пакеты» (тогда был бы timeout, а не `Connection closed`).

---

## Инфраструктура и файлы

**VPS:** `ssh -p 41480 botas@132.243.214.3`, проект в `/home/botas/dzen-bot`, systemd-юниты `xvfb.service` + `dzen-bot.service`.

**`dzen_state.json` содержит живые сессионные куки Яндекса — это доступ к аккаунту. В git не коммитить** (уже в `.gitignore`, как и `.wrangler/`).

**Ключи в `.env`:** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_ID`, `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_MODEL`, `LLM_PROVIDER`, `ANTHROPIC_*`, `DZEN_HEADLESS`, `DZEN_EDITOR_URL`, `DZEN_*_TIMEOUT_MS`, `PLAYWRIGHT_USER_DATA_DIR`, `SQLITE_PATH`, `DATA_DIR`, `LOG_LEVEL`.

**Диагностические утилиты в корне:** `debug_cover.py`, `debug_dzen.py`, `debug_publish.py`, `check_db.py`, `check_tables.py`, `test_db_init.py`. `tools/record_cover_upload.py` — подбор Playwright-селекторов для загрузки обложки.
