# -*- coding: utf-8 -*-
"""Исследование механизмов отдачи данных Яндекс Дзена.

Проверяет 4 способа получить данные без браузера:
  1. Прямые JSON/API эндпоинты
  2. RSS/Atom фиды каналов
  3. Встроенные JSON-данные в HTML страницы канала
  4. Sitemap

Запуск:  python tools/dzen_explorer.py
Зависимости: только requests + стандартная библиотека.
Playwright НЕ используется — это разведка, не парсинг.

Итог — таблица «что сработало / что нет» в конце вывода.
"""

import json
import re
import sys
import xml.etree.ElementTree as ET

import requests

# Windows-консоль может быть в cp1251 — принудительно utf-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TIMEOUT = 10

# Заголовки обычного Chrome на Windows
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

# Тестовые каналы для проверок, где нужен конкретный канал.
# Пробуем по очереди — вдруг какой-то slug не существует.
TEST_CHANNELS = ["tinkoffjournal", "sravni", "fincult"]

# Сюда складываются результаты всех проверок для итоговой таблицы
RESULTS = []


# ------------------------------------------------------------------ helpers

def fetch(url, params=None):
    """GET с общими заголовками. Возвращает (response | None, err | None)."""
    try:
        resp = requests.get(
            url, params=params, headers=HEADERS, timeout=TIMEOUT,
            allow_redirects=True,
        )
        return resp, None
    except requests.RequestException as exc:
        return None, f"{type(exc).__name__}: {exc}"


def redirect_note(resp):
    """Если были редиректы — куда в итоге приехали (важно: Дзен любит слать на SSO)."""
    if resp.history:
        return f"редирект {resp.history[0].status_code} -> {resp.url[:100]}"
    return ""


def describe_json(data, indent=2, max_items=15):
    """Показать структуру JSON: ключи и типы, но не значения."""
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


def report(method, name, status, data_type, fields="", note=""):
    """Печать блока результата + запись в итоговую таблицу."""
    print(f"\n[{method}] {name}")
    print(f"  Статус: {status}")
    print(f"  Тип данных: {data_type}")
    if fields:
        print(f"  Полезные поля: {fields}")
    if note:
        print(f"  Примечание: {note}")
    RESULTS.append((method, name, status, data_type, note))


def header(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


# ------------------------------------------------------- 1. API эндпоинты

def check_api_endpoints():
    header("1. ПРЯМЫЕ JSON/API ЭНДПОИНТЫ")
    channel = TEST_CHANNELS[0]
    endpoints = [
        ("launcher/feed", "https://dzen.ru/api/v3/launcher/feed", None),
        (
            "publisher/channel/articles",
            f"https://dzen.ru/api/v3/publisher/channel/{channel}/articles",
            None,
        ),
        (
            "media-api/channel/feed",
            "https://dzen.ru/media-api/channel/feed",
            {"channel_name": channel},
        ),
        (
            "legacy launcher/more",
            "https://zen.yandex.ru/api/v3/launcher/more",
            {"channel_name": channel},
        ),
    ]

    for name, url, params in endpoints:
        resp, err = fetch(url, params)
        if err:
            report("API", name, "FAIL", "недоступно", note=err)
            continue

        ctype = resp.headers.get("Content-Type", "?")
        note = redirect_note(resp)

        if "json" in ctype and resp.status_code == 200:
            try:
                data = resp.json()
            except ValueError:
                report("API", name, "PARTIAL", ctype,
                       note=f"HTTP {resp.status_code}, JSON не распарсился. {note}")
                continue
            print(f"\n[API] {name} — структура ответа:")
            describe_json(data)
            fields = ", ".join(list(data.keys())[:10]) if isinstance(data, dict) else ""
            report("API", name, "OK", "JSON", fields=fields, note=note)
        else:
            report(
                "API", name, "FAIL",
                "HTML" if "html" in ctype else ctype,
                note=f"HTTP {resp.status_code}. {note}".strip(),
            )


# ------------------------------------------------------------ 2. RSS фиды

def check_rss():
    header("2. RSS/ATOM ФИДЫ")

    for channel in TEST_CHANNELS:
        for name, url in [
            (f"rss/{channel}", f"https://dzen.ru/rss/{channel}"),
            (f"{channel}?format=rss", f"https://dzen.ru/{channel}?format=rss"),
        ]:
            resp, err = fetch(url)
            if err:
                report("RSS", name, "FAIL", "недоступно", note=err)
                continue

            ctype = resp.headers.get("Content-Type", "?")
            note = redirect_note(resp)
            body = resp.text[:500_000]

            looks_like_xml = "xml" in ctype or body.lstrip().startswith("<?xml")
            if resp.status_code != 200 or not looks_like_xml:
                report(
                    "RSS", name, "FAIL",
                    "HTML" if "html" in ctype else ctype,
                    note=f"HTTP {resp.status_code}. {note}".strip(),
                )
                continue

            # Парсим и смотрим, какие поля есть у item/entry
            try:
                root = ET.fromstring(resp.content)
            except ET.ParseError as exc:
                report("RSS", name, "PARTIAL", "XML",
                       note=f"XML не распарсился: {exc}. {note}")
                continue

            items = root.findall(".//item") or root.findall(
                ".//{http://www.w3.org/2005/Atom}entry"
            )
            if not items:
                report("RSS", name, "PARTIAL", "XML",
                       note=f"XML есть, но <item>/<entry> не найдены. {note}")
                continue

            # Собираем имена полей первого item (без namespace-мусора)
            fields = sorted({
                child.tag.split("}")[-1] for child in items[0]
            })
            report(
                "RSS", name, "OK", "XML/RSS",
                fields=", ".join(fields),
                note=f"элементов в фиде: {len(items)}. {note}".strip(),
            )


# ------------------------------------------------ 3. HTML страницы канала

# Паттерны встроенных данных, которые встречаются у Яндекса
EMBED_PATTERNS = [
    ("__INITIAL_STATE__", r"__INITIAL_STATE__\s*=\s*(\{)"),
    ("window.__data", r"window\.__data\s*=\s*(\{)"),
    ("window._data", r"window\._data\s*=\s*(\{)"),
    ("__serverState", r"__serverState\w*\s*=\s*(\{)"),
    ("Apollo state", r"__APOLLO_STATE__\s*=\s*(\{)"),
]


def extract_json_after(html, start_pos):
    """Вырезать сбалансированный {...} начиная с start_pos (позиция '{')."""
    depth = 0
    in_string = False
    escape = False
    for i in range(start_pos, min(len(html), start_pos + 3_000_000)):
        ch = html[i]
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
                return html[start_pos:i + 1]
    return None


def check_html():
    header("3. HTML-СТРАНИЦА КАНАЛА")

    pages = [("dzen.ru/finance", "https://dzen.ru/finance")] + [
        (f"dzen.ru/{ch}", f"https://dzen.ru/{ch}") for ch in TEST_CHANNELS[:2]
    ]

    for name, url in pages:
        resp, err = fetch(url)
        if err:
            report("HTML", name, "FAIL", "недоступно", note=err)
            continue

        note = redirect_note(resp)
        if "sso.passport" in resp.url or "captcha" in resp.url:
            report("HTML", name, "FAIL", "HTML",
                   note=f"унесло на SSO/капчу: {note}")
            continue
        if resp.status_code != 200:
            report("HTML", name, "FAIL", "HTML",
                   note=f"HTTP {resp.status_code}. {note}".strip())
            continue

        html = resp.text
        found_notes = [f"размер HTML: {len(html) // 1024} КБ"]
        parsed_any = False

        # <script type="application/json">
        json_scripts = re.findall(
            r'<script[^>]+type="application/(?:ld\+)?json"[^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        if json_scripts:
            found_notes.append(f'script type=json: {len(json_scripts)} шт.')
            # Показываем структуру самого большого
            biggest = max(json_scripts, key=len)
            try:
                data = json.loads(biggest)
                print(f"\n[HTML] {name} — самый крупный <script type=json> "
                      f"({len(biggest) // 1024} КБ):")
                describe_json(data)
                parsed_any = True
            except ValueError:
                found_notes.append("крупнейший script-json не распарсился")

        # Известные глобальные переменные с состоянием
        for label, pattern in EMBED_PATTERNS:
            m = re.search(pattern, html)
            if not m:
                continue
            found_notes.append(f"найден {label}")
            raw = extract_json_after(html, m.start(1))
            if raw:
                try:
                    data = json.loads(raw)
                    print(f"\n[HTML] {name} — структура {label} "
                          f"({len(raw) // 1024} КБ):")
                    describe_json(data)
                    parsed_any = True
                except ValueError:
                    found_notes.append(f"{label} вырезан, но JSON невалиден "
                                       f"(вероятно JS-код, не чистый JSON)")

        # Мета-теги с данными
        metas = re.findall(
            r'<meta[^>]+(?:property|name)="((?:og|twitter|zen)[^"]*)"', html
        )
        if metas:
            uniq = sorted(set(metas))
            found_notes.append(f"мета-теги: {', '.join(uniq[:12])}")

        status = "OK" if parsed_any else ("PARTIAL" if len(found_notes) > 1 else "FAIL")
        report("HTML", name, status, "HTML+JSON" if parsed_any else "HTML",
               note="; ".join(found_notes + ([note] if note else [])))


# ------------------------------------------------------------- 4. Sitemap

def check_sitemap():
    header("4. SITEMAP")

    for name, url in [
        ("sitemap.xml", "https://dzen.ru/sitemap.xml"),
        ("sitemap_index.xml", "https://dzen.ru/sitemap_index.xml"),
    ]:
        resp, err = fetch(url)
        if err:
            report("SITEMAP", name, "FAIL", "недоступно", note=err)
            continue

        note = redirect_note(resp)
        body = resp.text
        looks_like_xml = body.lstrip().startswith("<?xml") or "<urlset" in body[:2000] \
            or "<sitemapindex" in body[:2000]

        if resp.status_code != 200 or not looks_like_xml:
            ctype = resp.headers.get("Content-Type", "?")
            report("SITEMAP", name, "FAIL",
                   "HTML" if "html" in ctype else ctype,
                   note=f"HTTP {resp.status_code}. {note}".strip())
            continue

        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as exc:
            report("SITEMAP", name, "PARTIAL", "XML", note=f"не распарсился: {exc}")
            continue

        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        children = root.findall("sm:sitemap/sm:loc", ns)
        urls = root.findall("sm:url/sm:loc", ns)

        if children:
            print(f"\n[SITEMAP] {name} — это индекс, вложенных sitemap: {len(children)}")
            for loc in children[:10]:
                print(f"    {loc.text}")
            if len(children) > 10:
                print(f"    ... ещё {len(children) - 10}")
            report("SITEMAP", name, "OK", "XML/индекс",
                   fields=f"{len(children)} вложенных sitemap", note=note)
        elif urls:
            sample = ", ".join((u.text or "")[:60] for u in urls[:3])
            report("SITEMAP", name, "OK", "XML/urlset",
                   fields=f"{len(urls)} URL", note=f"примеры: {sample}. {note}".strip())
        else:
            report("SITEMAP", name, "PARTIAL", "XML",
                   note=f"XML есть, но ни <sitemap>, ни <url> не найдено. {note}")


# ------------------------------------------------------------------- итог

def print_summary():
    header("ИТОГОВАЯ ТАБЛИЦА")
    col1, col2, col3 = 10, 34, 8
    print(f"{'МЕТОД':<{col1}} {'ПРОВЕРКА':<{col2}} {'СТАТУС':<{col3}} ТИП ДАННЫХ")
    print("-" * 70)
    for method, name, status, data_type, _ in RESULTS:
        print(f"{method:<{col1}} {name[:col2]:<{col2}} {status:<{col3}} {data_type}")

    ok = sum(1 for r in RESULTS if r[2] == "OK")
    partial = sum(1 for r in RESULTS if r[2] == "PARTIAL")
    fail = sum(1 for r in RESULTS if r[2] == "FAIL")
    print("-" * 70)
    print(f"OK: {ok}  |  PARTIAL: {partial}  |  FAIL: {fail}")


def main():
    print("Исследование механизмов отдачи данных Яндекс Дзена")
    print(f"Тестовые каналы: {', '.join(TEST_CHANNELS)}")

    check_api_endpoints()
    check_rss()
    check_html()
    check_sitemap()
    print_summary()


if __name__ == "__main__":
    main()
