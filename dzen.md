# Dzen_2 — состояние проекта

**Обновлено:** 2026-07-25

**Назначение:** автогенерация и публикация статей в Яндекс.Дзен (ниша «финансы, заработок, бытовая психология денег»). Управление через Telegram-бота. Локальная разработка на Windows (`F:\Zerocoder\Dzen_2`), боевой запуск — на VPS.

Архитектура и пайплайн описаны в `CLAUDE.md` — здесь только то, чего там нет: текущий статус, инфраструктура, что сделано и что осталось.

---

## Главный контекст: мы в России

Это определяет почти все технические решения. Прямых подключений к внешним API с российского VPS нет — всё идёт через прокси.

| Сервис | Как подключаемся | Важно |
|--------|------------------|-------|
| Telegram Bot API | Cloudflare Worker `telegram-api-proxy.botass740.workers.dev` | **НЕ УДАЛЯТЬ.** Без него VPS вообще не видит Telegram |
| OpenRouter (LLM + FLUX) | Cloudflare Worker `openrouter-proxy.botass740.workers.dev` | Создан в этой сессии: с VPS OpenRouter отдавал `403 Access denied by security policy` (гео-блок) |

Оба воркера на аккаунте Cloudflare `botass740`. Код и конфиг воркера OpenRouter — в `tools/cloudflare/`.

Адреса прокси подставляются через `.env`: `TELEGRAM_API_BASE_URL`, `OPENROUTER_BASE_URL`.

**Секреты:** в `.env` лежат API-ключи и токен бота. В логах, которые присылает пользователь, токен бота виден внутри URL прокси — никогда не повторять его в ответах.

---

## Что сделано (готово и работает)

### Генерация
- Полный пайплайн работает: матрица осей → темы → заголовки → план → статья → проверка → обложка.
- Абстракция LLM-клиента (`llm.py`) — можно переключать провайдера через `LLM_PROVIDER` (`openrouter_client.py` / `anthropic_client.py`).
- Этап проверки сюжета `story_check.py` + `story_check_prompt.txt`.
- Обложки: FLUX через OpenRouter. `flux_client.py` принимает `base_url` (был захардкожен `openrouter.ai` — исправлено, теперь тоже через прокси). Fallback на PIL-placeholder при сбое.
- Промты переписаны под качество: квоты на цифры/диалоги/бренды, запрет афоризмов, постпроцессор `_cut_second_ending()`.

### Устойчивость доставки в Telegram (сделано в этой сессии)
Проблема была в том, что статья и обложка генерировались нормально, но превью не доходило до Telegram — бесплатный прокси-воркер рвал соединение на больших загрузках. Один упавший `send` ронял всю выдачу превью, и пользователь видел ложное «Ошибка генерации».

Что добавлено в `app/telegram/bot.py`:
- Таймауты в **обеих** ветках `ApplicationBuilder` (прокси и прямая): `connect/read 30s`, `write 60s`, `pool 30s`. Дефолтные 5 секунд через прокси не выживали.
- `_retry_send(coro_factory, what=, attempts=4)` — ретраи с backoff на `NetworkError`/`TimedOut`, уважает `RetryAfter`.
- `_compress_for_preview(image_path, max_side=1280, quality=82)` — PIL, PNG 1.6 МБ → JPEG ~150–250 КБ.
- Доставка превью сделана нефатальной. Если превью не ушло, но статья создана — честное сообщение «Статья готова (ID: N), но превью не доставилось из-за сети. Открой её через /list или /queue».

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

---

## Что осталось сделать

1. **Первая тестовая публикация** через бота на VPS: `/generate` → кнопка «Опубликовать». Это единственный непроверенный участок цепочки.
2. Следить за памятью во время публикации: 1970 МБ + 2 ГБ swap, Chromium headful может упереться. Если ловим OOM — смотреть `dmesg | grep -i oom`.

---

## Известные грабли (проверено на практике)

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
