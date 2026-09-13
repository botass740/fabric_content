"""Сбор статистики нашего канала в Дзене.

1. Парсим 99 published из БД.
2. Для каждой находим реальный URL через API (по title/keyword).
3. Через requests + куки dzen_state.json собираем views/likes/comments.
4. Зайдём Playwright на страницу канала и статистики — подписчики, общие
   просмотры, нишевая статистика.

Не печатает cookies в transcript.
"""
import re
import json
import time
import sqlite3
import requests
from collections import Counter
from pathlib import Path

STATE = 'dzen_state.json'
DB = 'data/vps_sync/2026-09-07/app.sqlite3'
OUT_DIR = 'data/vps_sync/2026-09-07'
CHANNEL_ID = '637b09c7e1c5d415d437e6ab'  # найден из HTML нашей статьи

# -------- метрики с HTML страницы статьи --------
METRIC_PATTERNS = {
    'views': [
        re.compile(r'"publicationStatistics"\s*:\s*\{\s*"views"\s*:\s*(\d+)'),
        re.compile(r'"views"\s*:\s*(\d+)\s*,\s*"viewsTillEnd"'),
        re.compile(r'"views"\s*:\s*(\d+)\s*\}'),
    ],
    'likes': [re.compile(r'"likeCount"\s*:\s*(\d+)')],
    'comments': [re.compile(r'"commentsCount"\s*:\s*(\d+)')],
    'time_to_read': [re.compile(r'"timeToReadSeconds"\s*:\s*(\d+)')],
}


def first_int(html, patterns):
    for p in patterns:
        m = p.search(html)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None


def extract_metrics(html):
    return {
        'views': first_int(html, METRIC_PATTERNS['views']),
        'likes': first_int(html, METRIC_PATTERNS['likes']),
        'comments': first_int(html, METRIC_PATTERNS['comments']),
        'time_to_read': first_int(html, METRIC_PATTERNS['time_to_read']),
    }


# -------- HTTP session с куками --------
def make_session():
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.9',
        'Referer': 'https://dzen.ru/',
    })
    state = json.loads(Path(STATE).read_text(encoding='utf-8'))
    loaded = 0
    for c in state.get('cookies', []):
        dom = c.get('domain', '')
        if 'dzen.ru' in dom or 'yandex.ru' in dom:
            s.cookies.set(c['name'], c['value'], domain=dom.lstrip('.'), path=c.get('path', '/'))
            loaded += 1
    print(f'[net] cookies loaded: {loaded}')
    return s


# -------- вытащить dzen_id (article slug) из HTML --------
# В HTML страницы статьи обычно есть "publicId" или "itemId"
def extract_article_id(html):
    # попробуем несколько regex
    for pat in [
        r'"itemId"\s*:\s*"([A-Za-z0-9_-]{8,32})"',
        r'"publicId"\s*:\s*"([A-Za-z0-9_-]{8,32})"',
        r'/a/([A-Za-z0-9_-]{8,32})',
    ]:
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return None


# -------- статистика канала через /api/v3/launcher/export --------
# (та же endpoint, что и в HTML страницах статей)
def channel_export(sess, limit=200):
    """Скачивает выгрузку канала — список статей с views/likes."""
    url = f'https://dzen.ru/api/v3/launcher/export'
    params = {
        'channel_id': CHANNEL_ID,
        'limit': limit,
    }
    headers = {
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json',
    }
    r = sess.get(url, params=params, headers=headers, timeout=20)
    print(f'[export] status={r.status_code} len={len(r.text)}')
    if r.status_code != 200:
        return None
    try:
        return r.json()
    except Exception as e:
        print(f'[export] json error: {e}')
        return None


# -------- статистика канала через /profile/editor/<channel_id>/statistics --------
def channel_stats_html(sess):
    """Открываем страницу статистики канала в HTML."""
    candidates = [
        f'https://dzen.ru/profile/editor/{CHANNEL_ID}/statistics',
        f'https://dzen.ru/id/{CHANNEL_ID}/statistics',
        f'https://dzen.ru/api/v3/launcher/channel?id={CHANNEL_ID}',
    ]
    out = {}
    for url in candidates:
        try:
            r = sess.get(url, timeout=20, allow_redirects=True)
            out[url] = {
                'status': r.status_code,
                'final_url': r.url,
                'len': len(r.text),
            }
            if r.status_code == 200:
                # subscribers
                m1 = re.search(r'"subscribersCount"\s*:\s*(\d+)', r.text)
                m2 = re.search(r'"subscribers"\s*:\s*\{[^}]*"count"\s*:\s*(\d+)', r.text)
                m3 = re.search(r'(\d[\d\s]*)\s*подписчик', r.text)
                m4 = re.search(r'"totalViews"\s*:\s*(\d+)', r.text)
                m5 = re.search(r'"viewsCount"\s*:\s*(\d+)', r.text)
                m6 = re.search(r'"channelTitle"\s*:\s*"([^"]+)"', r.text)
                m7 = re.search(r'"name"\s*:\s*"([^"]+)"\s*,\s*"description"', r.text)
                out[url].update({
                    'subscribersCount': m1.group(1) if m1 else None,
                    'subscribers_obj': m2.group(1) if m2 else None,
                    'subscribers_text': m3.group(0) if m3 else None,
                    'totalViews': m4.group(1) if m4 else None,
                    'viewsCount': m5.group(1) if m5 else None,
                    'channelTitle': m6.group(1) if m6 else None,
                    'name': m7.group(1) if m7 else None,
                })
                # сохранить первый 5000 символов для диагностики
                if len(r.text) < 100000:
                    out[url]['head'] = r.text[:5000]
        except Exception as e:
            out[url] = {'error': str(e)}
    return out


def main():
    # Шаг 1: смотрим, какие URL мы уже знаем из лога
    log_urls = []
    with open(f'{OUT_DIR}/app.log', encoding='utf-8', errors='replace') as f:
        log_text = f.read()
    for m in re.finditer(r'https://dzen\.ru/a/[A-Za-z0-9_-]+', log_text):
        log_urls.append(m.group(0))
    log_urls = list(set(log_urls))
    print(f'[log] unique /a/ URLs: {len(log_urls)}')

    # Шаг 2: подгружаем из БД список published
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    pub = conn.execute("SELECT id, title, created_at, published_at FROM articles WHERE status='published' ORDER BY id").fetchall()
    print(f'[db] published: {len(pub)}')

    # Шаг 3: для каждой published-статьи ищем URL в логе (по article_id из title нельзя —
    # id в URL — это dzen_id, а не наш rowid)
    # Пробуем через API export
    sess = make_session()
    print()
    print('=== channel_export ===')
    export = channel_export(sess, limit=200)
    if export:
        # Сканируем все поля export
        out_path = f'{OUT_DIR}/channel_export.json'
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(export, f, ensure_ascii=False, indent=2)
        print(f'[export] saved to {out_path}')
        # Что внутри
        if isinstance(export, dict):
            for k, v in export.items():
                if isinstance(v, list):
                    print(f'  {k}: list[{len(v)}]')
                elif isinstance(v, dict):
                    print(f'  {k}: dict({len(v)})')
                else:
                    s = str(v)[:80]
                    print(f'  {k}: {s}')
        elif isinstance(export, list):
            print(f'  list[{len(export)}]')
            if export:
                first = export[0]
                if isinstance(first, dict):
                    print(f'  first item keys: {list(first.keys())[:20]}')

    # Шаг 4: статистика канала
    print()
    print('=== channel_stats_html ===')
    stats = channel_stats_html(sess)
    out_path = f'{OUT_DIR}/channel_stats_probe.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f'[stats] saved to {out_path}')
    for url, data in stats.items():
        if 'error' in data:
            print(f'  {url[:80]}: ERROR {data["error"]}')
        else:
            print(f'  {url[:80]}: status={data.get("status")} final={data.get("final_url","")[:80]}')
            for k in ('subscribersCount', 'totalViews', 'viewsCount', 'channelTitle', 'name'):
                v = data.get(k)
                if v:
                    print(f'      {k}: {v}')


if __name__ == '__main__':
    main()
