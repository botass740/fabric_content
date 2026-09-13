# -*- coding: utf-8 -*-
"""Одноразовый скрипт: ШАГ 1 (допарсить метрики) + ШАГ 2 (дособрать 4 канала).

Использует requests + куки из dzen_state.json (НЕ модифицирует его).
Пишет только в data/research.db. Существующие tools/*.py не трогает.

Запуск:
  python tools/fill_metrics_and_seed_channels.py probe         # 50 статей — проба
  python tools/fill_metrics_and_seed_channels.py all           # все 560
  python tools/fill_metrics_and_seed_channels.py seed          # 4 канала
  python tools/fill_metrics_and_seed_channels.py probe seed    # последовательно
"""
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from statistics import median

try:
    import requests
except ImportError:
    print("FAIL: requests не установлен. pip install requests")
    sys.exit(1)

# --- paths ---
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB_PATH = os.path.join(ROOT, "data", "research.db")
STATE_PATH = os.path.join(ROOT, "dzen_state.json")
# четыре целевых канала: (channel_id, slug, ожидаемая категория)
SEED_TARGETS = [
    (22, "knyazevinvest", "finance"),
    (25, "quote.rbc.ru", "finance"),
    (35, "fond", "skip_obvious_tv"),     # «Советское телевидение» — заведомо не финансы
    (39, "mredgarcross", "mixed"),       # микс тем
]
SEED_TARGET_SLUGS = {slug for _, slug, _ in SEED_TARGETS}

# --- настройки из задания ---
PROBE_N = 50
PAUSE_PROBE = 0.7
PAUSE_FULL = 1.5      # мягче для 560
PAUSE_SEED = 1.0
TARGET_PER_CHANNEL = 50
TIMEOUT = 15

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ----------------------------------------------------------------- парсер
# Метрики в HTML авторизованной страницы статьи — это уникальные по имени
# вхождения внутри одного из блоков `var _params=({...})`. Поиск JSON
# целиком через extract_json_after на 1.2 МБ HTML с 15+ блоками _params
# оказался ненадёжен (бесконечные петли на несбалансированных блоках).
# Поэтому парсим метрики regex'ом напрямую — поля уникальны и встречаются
# ровно по одному разу.
#
# Подтверждено эмпирически на /a/amRpKj9oqBJkz0B1:
#   "publicationStatistics":{"views":133131,...   (CTX реальный)
#   ...,"likeCount":576,"visibilityType":"all"...
#   ...,"commentsCount":301,"likeCount":576,...
#   ...,"timeToReadSeconds":79,"...               (в contentState)
# "shares" в HTML статьи отсутствует (нет репост-API у читателя).

_METRIC_PATTERNS = {
    # publicationStatistics может появляться в разных местах; берём
    # ближайший к началу контекст с views
    "views": [
        re.compile(r'"publicationStatistics"\s*:\s*\{\s*"views"\s*:\s*(\d+)'),
        re.compile(r'"views"\s*:\s*(\d+)\s*,\s*"viewsTillEnd"'),
    ],
    "likes": [
        re.compile(r'"likeCount"\s*:\s*(\d+)'),
    ],
    "comments": [
        re.compile(r'"commentsCount"\s*:\s*(\d+)'),
    ],
    "time_to_read": [
        re.compile(r'"timeToReadSeconds"\s*:\s*(\d+)'),
    ],
}


def _first_int(html, patterns):
    for p in patterns:
        m = p.search(html)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None


def extract_metrics_from_html(html):
    """Достать views/likes/comments/time_to_read/shares из HTML статьи.
    Возвращает dict (None если поле не нашлось)."""
    return {
        "views": _first_int(html, _METRIC_PATTERNS["views"]),
        "likes": _first_int(html, _METRIC_PATTERNS["likes"]),
        "comments": _first_int(html, _METRIC_PATTERNS["comments"]),
        "time_to_read": _first_int(html, _METRIC_PATTERNS["time_to_read"]),
        "shares": None,  # в HTML статьи нет
    }


# ----------------------------------------------------------------- сеть
def make_session():
    if not os.path.exists(STATE_PATH):
        print(f"FAIL: {STATE_PATH} не найден. Сначала python tools/dzen_login_local.py")
        sys.exit(2)
    with open(STATE_PATH, encoding="utf-8") as fh:
        state = json.load(fh)
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Referer": "https://dzen.ru/",
    })
    loaded = 0
    for c in state.get("cookies", []):
        dom = c.get("domain", "")
        if "dzen.ru" not in dom and "yandex.ru" not in dom:
            continue
        s.cookies.set(name=c["name"], value=c["value"],
                      domain=dom.lstrip("."),
                      path=c.get("path", "/"))
        loaded += 1
    print(f"[net] загружено {loaded} куков в сессию")
    return s


def fetch_article(session, url):
    """GET страницы статьи. Возвращает (metrics_dict | None, note_str)."""
    try:
        r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
    except requests.RequestException as exc:
        return None, f"REQ_FAIL: {type(exc).__name__}: {exc}"
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}"
    if "sso.passport" in r.url or "captcha" in r.url:
        return None, "SSO_REDIRECT"
    m = extract_metrics_from_html(r.text)
    if m["views"] is None and m["likes"] is None and m["comments"] is None:
        return None, "NO_METRICS"
    return m, "OK"


# ----------------------------------------------------------------- БД
def db():
    return sqlite3.connect(DB_PATH)


def get_articles_missing_metrics(conn, limit=None):
    sql = ("SELECT id, url, title FROM articles "
           "WHERE url IS NOT NULL AND views IS NULL ORDER BY id")
    if limit:
        sql += f" LIMIT {int(limit)}"
    return list(conn.execute(sql).fetchall())


def update_article_metrics(conn, article_id, metrics):
    conn.execute(
        "UPDATE articles SET views=?, likes=?, comments=?, shares=?, time_to_read=? "
        "WHERE id=?",
        (metrics["views"], metrics["likes"], metrics["comments"],
         metrics["shares"], metrics["time_to_read"], article_id),
    )


def ensure_column(conn, table, col, decl):
    """Добавить колонку если её нет (для time_to_read)."""
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {decl}")
        print(f"[db] добавлена колонка {table}.{col}")


# ----------------------------------------------------------------- ШАГ 1
def step1_fill_metrics(mode):
    conn = db()
    ensure_column(conn, "articles", "time_to_read", "time_to_read INTEGER")
    if mode == "probe":
        rows = get_articles_missing_metrics(conn, limit=PROBE_N)
        pause = PAUSE_PROBE
    else:
        rows = get_articles_missing_metrics(conn, limit=None)
        pause = PAUSE_FULL

    print(f"\n[step1] всего к обходу: {len(rows)} статей, пауза {pause}s")
    sess = make_session()

    updated, failed = 0, []
    t0 = time.time()
    for i, (aid, url, title) in enumerate(rows, 1):
        m, note = fetch_article(sess, url)
        if note == "OK":
            update_article_metrics(conn, aid, m)
            conn.commit()
            updated += 1
        else:
            failed.append((aid, url, note))
        if i % 20 == 0 or i == len(rows):
            elapsed = time.time() - t0
            print(f"  [{i}/{len(rows)}] updated={updated}, failed={len(failed)}, "
                  f"elapsed={elapsed:.1f}s")
        if i < len(rows):
            time.sleep(pause)
    conn.close()

    # отчёт
    print(f"\n[step1] ИТОГ: updated={updated}, failed={len(failed)}")
    if failed:
        # счёт по причинам
        from collections import Counter
        c = Counter(n for _, _, n in failed)
        print("[step1] причины пропусков:", dict(c))
        print("[step1] первые 5 неудач:")
        for aid, url, note in failed[:5]:
            print(f"  id={aid} {url[:80]}... → {note}")
    return updated, failed


# ----------------------------------------------------------------- ШАГ 2
def fetch_channel_feed(session, slug, limit=20):
    """Получить JSON ленты канала. Пробуем несколько эндпоинтов."""
    endpoints = [
        ("https://dzen.ru/api/v3/launcher/feed",
         {"channel_name": slug, "limit": limit}),
        ("https://dzen.ru/media-api/channel/articles",
         {"channel_name": slug, "limit": limit}),
    ]
    for url, params in endpoints:
        try:
            r = session.get(url, params=params, timeout=TIMEOUT)
        except requests.RequestException:
            continue
        if r.status_code != 200:
            continue
        ctype = r.headers.get("Content-Type", "")
        if "json" not in ctype:
            continue
        try:
            data = r.json()
        except ValueError:
            continue
        items = _extract_items_from_feed(data)
        if items:
            return items
    # fallback: страница канала
    return _items_from_channel_page(session, slug, limit)


def _extract_items_from_feed(data):
    if isinstance(data, dict):
        for k in ("items", "data", "feed", "publications", "results"):
            v = data.get(k)
            if isinstance(v, list) and v and isinstance(v[0], dict):
                if "url" in v[0] or "link" in v[0] or "id" in v[0]:
                    return v
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data
    return []


def _items_from_channel_page(session, slug, limit):
    try:
        r = session.get(f"https://dzen.ru/{slug}", timeout=TIMEOUT)
    except requests.RequestException:
        return []
    if r.status_code != 200:
        return []
    # 1) попробуем найти <script type="application/ld+json"> с ItemList
    for block in re.findall(
        r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
        r.text, re.DOTALL,
    ):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "ItemList":
            el_list = data.get("itemListElement")
            if isinstance(el_list, list):
                items = []
                for el in el_list:
                    if not isinstance(el, dict):
                        continue
                    obj = el.get("item") or el.get("url") or el
                    if isinstance(obj, dict):
                        items.append(obj)
                    elif isinstance(obj, str):
                        items.append({"url": obj})
                if items:
                    return items[:limit]
    # 2) попробуем найти exportResponse.feedData.items в JSON-блоках
    #    (для страниц канала Dzen встраивает данные в <script>var _params=...
    #    но из-за многообразия блоков ищем по ключу напрямую)
    m = re.search(
        r'"exportResponse"\s*:\s*\{[^{}]*"feedData"\s*:\s*\{[^{}]*"items"\s*:\s*(\[[^\]]+\])',
        r.text,
    )
    if m:
        try:
            items = json.loads(m.group(1))
            if isinstance(items, list):
                return items[:limit]
        except ValueError:
            pass
    return []


def step2_seed_channels():
    conn = db()
    sess = make_session()
    total_new = 0
    summary = []

    for cid, slug, _cat in SEED_TARGETS:
        print(f"\n[step2] === {slug} (channel_id={cid}) ===")
        items = fetch_channel_feed(sess, slug, limit=TARGET_PER_CHANNEL)
        if not items:
            print(f"  EMPTY: ни API, ни страница не отдали ленту")
            summary.append((slug, 0, 0, 0, "no_feed"))
            continue

        print(f"  получено {len(items)} элементов из ленты")
        new_for_channel = 0
        for it in items:
            url = it.get("url") or it.get("link") or it.get("shareLink")
            if not url:
                continue
            if not url.startswith("http"):
                url = "https://dzen.ru" + (url if url.startswith("/") else "/" + url)
            dzen_id = it.get("id") or it.get("itemId")
            title = it.get("title") or ""
            published_at = (it.get("publicationDate") or it.get("date") or "")
            # нормализуем формат даты
            if isinstance(published_at, str) and published_at:
                # Dzen отдаёт '2024-09-19T12:34:56.000Z'
                pass

            # проверяем, есть ли уже в БД
            exists = conn.execute(
                "SELECT 1 FROM articles WHERE url=? OR dzen_id=?",
                (url, str(dzen_id) if dzen_id else ""),
            ).fetchone()
            if exists:
                continue

            # забираем метрики сразу, чтобы сэкономить проход
            m, note = fetch_article(sess, url)
            time.sleep(PAUSE_SEED)
            row = {
                "dzen_id": str(dzen_id) if dzen_id else url.rsplit("/", 1)[-1],
                "channel_id": cid,
                "url": url,
                "title": title,
                "text": "",  # нам сейчас метрики нужнее, чем полные тексты
                "text_length": 0,
                "word_count": 0,
                "published_at": published_at,
                "views": m["views"] if m else None,
                "likes": m["likes"] if m else None,
                "comments": m["comments"] if m else None,
                "shares": m["shares"] if m else None,
                "time_to_read": m["time_to_read"] if m else None,
            }
            try:
                conn.execute(
                    """INSERT INTO articles
                       (dzen_id, channel_id, url, title, text, text_length,
                        word_count, published_at, views, likes, comments,
                        shares, time_to_read, is_parsed, is_analyzed)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)""",
                    (row["dzen_id"], row["channel_id"], row["url"],
                     row["title"], row["text"], row["text_length"],
                     row["word_count"], row["published_at"],
                     row["views"], row["likes"], row["comments"],
                     row["shares"], row["time_to_read"]),
                )
                new_for_channel += 1
                total_new += 1
            except sqlite3.IntegrityError as exc:
                print(f"    DUP: {url[:80]} ({exc})")
        conn.commit()

        # обновим articles_count в channels
        actual = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE channel_id=?", (cid,)
        ).fetchone()[0]
        conn.execute(
            "UPDATE channels SET articles_count=?, last_crawled_at=? WHERE id=?",
            (actual, datetime.now(timezone.utc).isoformat(), cid),
        )
        conn.commit()
        print(f"  новых: {new_for_channel}, всего в БД по каналу: {actual}")
        summary.append((slug, len(items), new_for_channel, actual, "ok"))

    conn.close()
    print(f"\n[step2] ВСЕГО НОВЫХ СТАТЕЙ: {total_new}")
    print("[step2] сводка:")
    print(f"  {'slug':<18} {'получено':<10} {'новых':<8} {'в БД':<8} статус")
    for slug, got, new, total, status in summary:
        print(f"  {slug:<18} {got:<10} {new:<8} {total:<8} {status}")
    return total_new, summary


# ----------------------------------------------------------------- main
def main():
    args = sys.argv[1:] or ["probe", "seed"]
    if "probe" in args:
        print("\n" + "=" * 60 + "\nПРОБА (50 статей)\n" + "=" * 60)
        step1_fill_metrics("probe")
    if "all" in args:
        print("\n" + "=" * 60 + "\nПОЛНЫЙ ПРОГОН (все 560)\n" + "=" * 60)
        step1_fill_metrics("all")
    if "seed" in args:
        print("\n" + "=" * 60 + "\nШАГ 2: 4 КАНАЛА ИЗ SEED\n" + "=" * 60)
        step2_seed_channels()


if __name__ == "__main__":
    main()
