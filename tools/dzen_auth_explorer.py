# -*- coding: utf-8 -*-
"""Проверка двух стратегий сбора данных с Дзена ПОД АВТОРИЗАЦИЕЙ.

Часть 1: requests.Session + куки из dzen_state.json (Playwright state).
Часть 2: Playwright + перехват XHR (запускается только если PLAYWRIGHT_NEEDED=True).

Запуск: python tools/dzen_auth_explorer.py
Зависимости: requests + playwright (обе уже в requirements.txt).

Скрипт не падает при ошибках — всё перехватывается и логируется.
"""

import json
import os
import re
import sys

import requests

# Windows-консоль может быть в cp1251 — принудительно utf-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ----------------------------------------------------------- КОНСТАНТЫ
# Путь до state ищем и в корне проекта, и рядом со скриптом
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
DZEN_STATE_PATH = os.path.join(_ROOT, "dzen_state.json")

TEST_CHANNEL = "fainmanomica"  # уточни slug из URL канала
TEST_ARTICLE_URL = "https://dzen.ru/a/amRpKj9oqBJkz0B1"  # статья с канала tbank
PLAYWRIGHT_NEEDED = False       # переключить в True, если requests не дал данных

TIMEOUT = 10

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://dzen.ru/",
}

# Собираем сюда флаги успеха для финальной рекомендации.
# req_* — результат requests+куки; pw_* — результат Playwright.
STATE = {
    "req_channel_html_ok": False,   # страница канала отдалась без SSO (requests)
    "req_channel_json": False,      # в HTML канала нашли встроенный JSON (requests)
    "req_api_ok": False,            # API отдал ОСМЫСЛЕННЫЙ JSON статей (requests)
    "req_article_ok": False,        # страница статьи отдалась (requests)
    "pw_authenticated": False,      # браузер зашёл авторизованным (служебные API 200)
    "pw_feed_found": False,         # пойман XHR ленты статей с данными
    "pw_html_data": False,          # в HTML канала (браузер) есть встроенный JSON
    "pw_auth_warning": "",          # напр. протухший VK-автологин
}

# По этим кускам URL узнаём именно ленту публикаций (а не служебные API)
FEED_URL_HINTS = (
    "launcher/more", "launcher/export", "channel/articles",
    "channel/feed", "media-api/channel", "/publications", "publisher-feed",
)

# ------------------------------------------------------------- ХЕЛПЕРЫ

def header(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def is_sso(resp):
    """Унесло ли на паспорт/капчу Яндекса."""
    return "sso.passport" in resp.url or "captcha" in resp.url or "/auth/" in resp.url


def describe_json(data, indent=2, max_items=20):
    """Показать структуру JSON: ключи и типы, без значений."""
    pad = " " * indent
    if isinstance(data, dict):
        for i, (key, value) in enumerate(data.items()):
            if i >= max_items:
                print(f"{pad}... ещё {len(data) - max_items} ключей")
                break
            if isinstance(value, dict):
                print(f"{pad}{key}: dict ({len(value)} ключей)")
            elif isinstance(value, list):
                inner = type(value[0]).__name__ if value else "?"
                print(f"{pad}{key}: list[{inner}] x{len(value)}")
            else:
                print(f"{pad}{key}: {type(value).__name__}")
    elif isinstance(data, list):
        print(f"{pad}list из {len(data)} элементов")
        if data and isinstance(data[0], dict):
            print(f"{pad}ключи первого элемента:")
            describe_json(data[0], indent + 2, max_items)


def extract_json_after(text, start_pos):
    """Вырезать сбалансированный {...} начиная с позиции '{' в start_pos."""
    depth = 0
    in_string = False
    escape = False
    for i in range(start_pos, min(len(text), start_pos + 3_000_000)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start_pos:i + 1]
    return None


def find_embedded_json(html):
    """Ищем встроенные данные в HTML страницы канала.

    Возвращает список (метка, распарсенный объект).
    """
    found = []

    # Глобальные переменные состояния
    patterns = [
        ("window.__data", r"window\.__data\s*=\s*(\{)"),
        ("__INITIAL_STATE__", r"__INITIAL_STATE__\s*=\s*(\{)"),
        ("window._data", r"window\._data\s*=\s*(\{)"),
    ]
    for label, pattern in patterns:
        m = re.search(pattern, html)
        if not m:
            continue
        raw = extract_json_after(html, m.start(1))
        if not raw:
            print(f"    {label}: найден, но {{}} не сбалансировался")
            continue
        try:
            found.append((label, json.loads(raw)))
        except ValueError:
            print(f"    {label}: вырезан ({len(raw) // 1024} КБ), "
                  f"но невалидный JSON (вероятно JS-выражение)")

    # <script type="application/json">
    for block in re.findall(
        r'<script[^>]+type="application/(?:ld\+)?json"[^>]*>(.*?)</script>',
        html, re.DOTALL,
    ):
        try:
            found.append(("script[type=json]", json.loads(block)))
        except ValueError:
            pass

    # data-state="..."
    m = re.search(r'data-state="([^"]+)"', html)
    if m:
        print("    data-state=: атрибут присутствует (HTML-экранирован)")

    return found


def load_cookies_into_session():
    """Загрузить куки Playwright-state в requests.Session.

    Возвращает Session либо None (если файла нет / он битый).
    """
    if not os.path.exists(DZEN_STATE_PATH):
        print("\n[ОШИБКА] dzen_state.json не найден по пути:")
        print(f"    {DZEN_STATE_PATH}")
        print("Как получить: запусти локально `python tools/dzen_login_local.py`,")
        print("войди в аккаунт Дзена в открывшемся браузере — он сохранит dzen_state.json.")
        return None

    try:
        with open(DZEN_STATE_PATH, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"\n[ОШИБКА] dzen_state.json не читается: {exc}")
        return None

    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)

    loaded = 0
    for cookie in state.get("cookies", []):
        domain = cookie.get("domain", "")
        # Берём только куки Дзена и Яндекса — остальное (vk, mail) не нужно
        if "dzen.ru" not in domain and "yandex.ru" not in domain:
            continue
        try:
            session.cookies.set(
                name=cookie["name"],
                value=cookie["value"],
                domain=domain.lstrip("."),
                path=cookie.get("path", "/"),
            )
            loaded += 1
        except Exception as exc:  # noqa: BLE001 — кука не должна ронять скрипт
            print(f"    кука {cookie.get('name')!r} пропущена: {exc}")

    print(f"\nЗагружено куков в сессию: {loaded} "
          f"(из {len(state.get('cookies', []))} в файле)")
    return session


def get(session, url, params=None):
    """GET через сессию. Возвращает (resp | None, err | None)."""
    try:
        resp = session.get(url, params=params, timeout=TIMEOUT, allow_redirects=True)
        return resp, None
    except requests.RequestException as exc:
        return None, f"{type(exc).__name__}: {exc}"


def check_channel_page(session):
    """3.1 — страница канала: отдаётся ли HTML и есть ли встроенный JSON."""
    header("3.1 СТРАНИЦА КАНАЛА (requests + куки)")
    url = f"https://dzen.ru/{TEST_CHANNEL}"
    resp, err = get(session, url)
    if err:
        print(f"  FAIL: {err}")
        return
    print(f"  URL после редиректов: {resp.url[:110]}")
    print(f"  HTTP {resp.status_code}, Content-Type: {resp.headers.get('Content-Type', '?')}")

    if is_sso(resp):
        print("  FAIL: унесло на SSO/капчу — куки не приняты для этой страницы")
        return
    if resp.status_code != 200 or "html" not in resp.headers.get("Content-Type", ""):
        print("  FAIL: не HTML или не 200 (Дзен вернул страницу-ошибку)")
        return

    STATE["req_channel_html_ok"] = True
    html = resp.text
    print(f"  OK: HTML получен, {len(html) // 1024} КБ. Ищу встроенный JSON:")

    found = find_embedded_json(html)
    if not found:
        print("    встроенный JSON не найден")
        return
    STATE["req_channel_json"] = True
    for label, data in found:
        print(f"\n  >>> {label} — ключи верхнего уровня:")
        describe_json(data)


def check_api_endpoints(session):
    """3.2 — API эндпоинты с куками."""
    header("3.2 API ЭНДПОИНТЫ (requests + куки)")
    endpoints = [
        ("launcher/feed",
         "https://dzen.ru/api/v3/launcher/feed",
         {"channel_name": TEST_CHANNEL, "limit": 20}),
        ("media-api/channel/articles",
         "https://dzen.ru/media-api/channel/articles",
         {"channel_name": TEST_CHANNEL, "limit": 20}),
        ("publisher/channel/articles",
         f"https://dzen.ru/api/v3/publisher/channel/{TEST_CHANNEL}/articles",
         {"limit": 20, "offset": 0}),
    ]
    for name, url, params in endpoints:
        print(f"\n[API] {name}")
        resp, err = get(session, url, params)
        if err:
            print(f"  FAIL: {err}")
            continue
        ctype = resp.headers.get("Content-Type", "?")
        print(f"  HTTP {resp.status_code}, Content-Type: {ctype}")
        if resp.history:
            print(f"  (редирект -> {resp.url[:90]})")
        if "json" not in ctype:
            print("  FAIL: ответ не JSON")
            continue
        try:
            data = resp.json()
        except ValueError:
            print("  PARTIAL: заявлен JSON, но не распарсился")
            continue
        # Не-200 = ошибка, чем бы ни было тело
        if resp.status_code != 200:
            print(f"  FAIL: HTTP {resp.status_code}, тело: {str(data)[:120]}")
            continue
        # Формы ошибок Дзена: {error, errtext} или {errors: [...]}
        if isinstance(data, dict) and (
            set(data.keys()) <= {"error", "errtext"} or "errors" in data
        ):
            print(f"  FAIL: ответ-ошибка {str(data)[:120]}")
            continue
        print("  OK: структура ответа:")
        describe_json(data)
        STATE["req_api_ok"] = True


def check_article_page(session):
    """3.3 — страница конкретной статьи."""
    header("3.3 СТРАНИЦА СТАТЬИ (requests + куки)")
    if not TEST_ARTICLE_URL:
        print("  ПРОПУСК: TEST_ARTICLE_URL пуст. Вставь URL статьи в константу "
              "в начале файла, чтобы проверить извлечение полей.")
        return
    resp, err = get(session, TEST_ARTICLE_URL)
    if err:
        print(f"  FAIL: {err}")
        return
    print(f"  URL после редиректов: {resp.url[:110]}")
    print(f"  HTTP {resp.status_code}")
    if is_sso(resp):
        print("  FAIL: унесло на SSO/капчу")
        return
    if resp.status_code != 200:
        print("  FAIL: не 200")
        return

    STATE["req_article_ok"] = True
    html = resp.text
    print(f"  OK: HTML статьи получен, {len(html) // 1024} КБ. Ищу поля:")

    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL)
    if h1:
        title = re.sub(r"<[^>]+>", "", h1.group(1)).strip()
        print(f"    заголовок (h1): {title[:90]!r}")
    else:
        print("    заголовок (h1): не найден")

    paras = re.findall(r"<p[^>]*>(.*?)</p>", html, re.DOTALL)
    print(f"    абзацев <p>: {len(paras)}")
    times = re.findall(r"<time[^>]*datetime=\"([^\"]+)\"", html)
    if times:
        print(f"    дата (<time datetime>): {times[0]}")
    else:
        print("    дата (<time>): не найдена")

    # Счётчики (просмотры/лайки) — есть ли встроенный JSON со статистикой
    found = find_embedded_json(html)
    if found:
        print(f"    встроенный JSON на странице статьи: {len(found)} блок(ов) "
              f"— вероятно, содержит счётчики")


def explore_with_playwright():
    """Часть 2 — открыть канал браузером с куками и перехватить XHR к API."""
    header("ЧАСТЬ 2. PLAYWRIGHT + ПЕРЕХВАТ XHR")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  FAIL: playwright не установлен (pip install playwright && "
              "playwright install chromium)")
        return

    if not os.path.exists(DZEN_STATE_PATH):
        print(f"  FAIL: {DZEN_STATE_PATH} не найден")
        return

    captured = []  # список dict: method, url, status, json_keys, is_feed

    def on_response(response):
        url = response.url
        if not any(k in url for k in ("api", "feed", "articles", "media-api")):
            return
        # Авторизация подтвердилась, если служебные API Дзена отдают 200
        if "dzen.ru/api" in url and response.status == 200:
            STATE["pw_authenticated"] = True
        # Признак протухшей сессии
        if "autologin" in url and ("errorCode" in url or "invalid" in url):
            STATE["pw_auth_warning"] = (
                "VK-автологин вернул ошибку (invalid user) — куки могут подтухать"
            )
        ctype = response.headers.get("content-type", "")
        is_feed = any(h in url for h in FEED_URL_HINTS)
        entry = {
            "method": response.request.method,
            "url": url,
            "status": response.status,
            "ctype": ctype,
            "json_keys": None,
            "is_feed": is_feed,
        }
        if "application/json" in ctype:
            try:
                data = response.json()
                if isinstance(data, dict):
                    entry["json_keys"] = list(data.keys())[:15]
                    # Лента с данными: URL похож на фид И это не ответ-ошибка
                    is_error = set(data.keys()) <= {"error", "errtext"} \
                        or "errors" in data
                    if is_feed and response.status == 200 and not is_error:
                        STATE["pw_feed_found"] = True
                elif isinstance(data, list):
                    entry["json_keys"] = [f"list x{len(data)}"]
                    if is_feed and response.status == 200 and data:
                        STATE["pw_feed_found"] = True
            except Exception:  # noqa: BLE001
                entry["json_keys"] = "<не распарсился>"
        captured.append(entry)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                storage_state=DZEN_STATE_PATH,
                user_agent=BROWSER_HEADERS["User-Agent"],
                locale="ru-RU",
            )
            page = context.new_page()
            page.on("response", on_response)

            url = f"https://dzen.ru/{TEST_CHANNEL}"
            print(f"  Открываю {url} ...")
            page.goto(url, wait_until="networkidle", timeout=40_000)
            print(f"  URL после загрузки: {page.url[:110]}")

            # Двойной скролл, чтобы подгрузилась лента (lazy-load через XHR)
            for _ in range(2):
                page.evaluate("window.scrollBy(0, 3000)")
                page.wait_for_timeout(3000)

            # Снимаем финальный HTML — вдруг лента в SSR (window.__data),
            # а не в отдельном XHR
            final_html = page.content()
            browser.close()
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL: Playwright упал: {type(exc).__name__}: {exc}")
        return

    # --- перехваченные сетевые запросы ---
    if captured:
        print(f"\n  Перехвачено релевантных запросов: {len(captured)}")
        for entry in captured:
            marker = " <-- ЛЕНТА?" if entry["is_feed"] else ""
            print(f"\n  [{entry['method']}] HTTP {entry['status']}{marker}")
            print(f"    {entry['url'][:150]}")
            if entry["json_keys"]:
                print(f"    JSON ключи: {entry['json_keys']}")
    else:
        print("  Перехваченных API-запросов нет.")

    # --- встроенный JSON в HTML страницы канала (SSR) ---
    print("\n  Разбор HTML страницы канала (браузерный рендер):")
    found = find_embedded_json(final_html)
    if found:
        STATE["pw_html_data"] = True
        for label, data in found:
            print(f"\n  >>> {label} — ключи верхнего уровня:")
            describe_json(data)
    else:
        print("    встроенный JSON (window.__data / script[type=json]) не найден")


def print_recommendation():
    header("РЕКОМЕНДАЦИЯ")

    # Сводка фактов, на которых основана рекомендация
    print("Факты:")
    print(f"  requests: страница канала        — "
          f"{'OK' if STATE['req_channel_html_ok'] else 'FAIL'}")
    print(f"  requests: встроенный JSON в HTML — "
          f"{'OK' if STATE['req_channel_json'] else 'FAIL'}")
    print(f"  requests: API-эндпоинты          — "
          f"{'OK' if STATE['req_api_ok'] else 'FAIL'}")
    print(f"  requests: страница статьи        — "
          f"{'OK' if STATE['req_article_ok'] else 'FAIL'}")
    print(f"  playwright: авторизация          — "
          f"{'OK' if STATE['pw_authenticated'] else 'FAIL / не запускался'}")
    print(f"  playwright: XHR с лентой статей  — "
          f"{'OK' if STATE['pw_feed_found'] else 'не найден'}")
    print(f"  playwright: JSON в HTML рендера  — "
          f"{'OK' if STATE['pw_html_data'] else 'не найден'}")
    if STATE["pw_auth_warning"]:
        print(f"  предупреждение: {STATE['pw_auth_warning']}")
    print()

    req_ok = STATE["req_api_ok"] or STATE["req_channel_json"]
    pw_ok = STATE["pw_feed_found"] or STATE["pw_html_data"]

    if req_ok:
        print("РЕКОМЕНДАЦИЯ: requests + куки — успешно.")
        print("  Данные доступны без браузера: краулер = requests.Session")
        print("  с куками из dzen_state.json. Самый дешёвый путь.")
    elif pw_ok and STATE["pw_feed_found"]:
        print("РЕКОМЕНДАЦИЯ: нужен Playwright XHR-перехват.")
        print("  requests+куки данные не дали, но браузер под авторизацией видит")
        print("  XHR с лентой статей. Краулер = Playwright + page.on('response'),")
        print("  либо воспроизвести эти же запросы через requests (см. URL выше).")
    elif pw_ok:
        print("РЕКОМЕНДАЦИЯ: нужен гибрид (Playwright-рендер + разбор HTML).")
        print("  Лента статей не приходит отдельным XHR — она отрисована сервером")
        print("  внутри страницы (SSR). Краулер: Playwright открывает страницу")
        print("  канала под авторизацией, скроллит, затем парсит window.__data /")
        print("  script[type=json] из page.content(). requests сам по себе не")
        print("  работает (канал отдаёт 404/SSO без браузера).")
    elif STATE["pw_authenticated"]:
        print("РЕКОМЕНДАЦИЯ: нужен Playwright, но источник данных не найден.")
        print("  Авторизация в браузере работает, однако ни XHR с лентой, ни")
        print("  встроенный JSON не обнаружены. Смотреть вывод Части 2 вручную:")
        print("  возможно, нужен другой канал (проверь, что TEST_CHANNEL")
        print("  существует) или другой шаблон страницы.")
    else:
        print("РЕКОМЕНДАЦИЯ: ничего не сработало — вероятно, протухли куки.")
        print("  Ни requests, ни Playwright не показали авторизацию. Перелогинься:")
        print("  python tools/dzen_login_local.py — и запусти разведку снова.")


def main():
    print("Проверка стратегий сбора данных Дзена ПОД АВТОРИЗАЦИЕЙ")
    print(f"Канал: {TEST_CHANNEL}")
    print(f"State-файл: {DZEN_STATE_PATH}")

    header("ЧАСТЬ 1. REQUESTS + КУКИ")
    session = load_cookies_into_session()
    if session is not None:
        for step in (check_channel_page, check_api_endpoints, check_article_page):
            try:
                step(session)
            except Exception as exc:  # noqa: BLE001 — ни один шаг не должен ронять скрипт
                print(f"  [исключение в {step.__name__}]: "
                      f"{type(exc).__name__}: {exc}")

    # Часть 2 — по флагу, либо автоматически если Часть 1 не дала данных
    need_pw = PLAYWRIGHT_NEEDED or not (
        STATE["req_api_ok"] or STATE["req_channel_json"]
    )
    if need_pw:
        if not PLAYWRIGHT_NEEDED:
            print("\n[инфо] requests не дал структурированных данных — "
                  "запускаю Playwright-разведку автоматически.")
        try:
            explore_with_playwright()
        except Exception as exc:  # noqa: BLE001
            print(f"  [исключение в explore_with_playwright]: "
                  f"{type(exc).__name__}: {exc}")
    else:
        print("\n[инфо] Часть 2 (Playwright) пропущена: requests уже дал данные. "
              "Поставь PLAYWRIGHT_NEEDED=True, чтобы всё равно подсмотреть XHR.")

    print_recommendation()


if __name__ == "__main__":
    main()

