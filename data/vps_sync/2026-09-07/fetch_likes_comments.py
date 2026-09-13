"""Сбор likes/comments с HTML страниц статей нашего канала.

Источник:
  data/vps_sync/2026-09-07/channel_all_articles.json — список 163 статей
  с publication_object_id, title, share_link (URL вида /a/<id>)

Парсит HTML каждой статьи через requests + куки dzen_state.json.
Обновляет channel_all_articles.json (дописывает поля likes, comments_from_html,
views_from_html, time_to_read_from_html, fetched_at).

Rate limit: 0.5s между запросами. На таймауте/404/HTTP>400 — пропуск.
"""
import json
import re
import time
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

STATE = 'dzen_state.json'
OUT_DIR = 'data/vps_sync/2026-09-07'
ARTICLES_PATH = f'{OUT_DIR}/channel_all_articles.json'

# Уникальные regex-паттерны для метрик
METRIC_PATTERNS = {
    'views': [
        re.compile(r'"publicationStatistics"\s*:\s*\{\s*"views"\s*:\s*(\d+)'),
        re.compile(r'"views"\s*:\s*(\d+)\s*,\s*"viewsTillEnd"'),
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
            except (ValueError, TypeError):
                continue
    return None


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


def fetch_one(sess, url, attempts=3):
    """Получить HTML страницы и спарсить метрики. Возвращает dict."""
    last_err = None
    for a in range(1, attempts + 1):
        try:
            r = sess.get(url, timeout=15, allow_redirects=True)
        except Exception as e:
            last_err = f'NET: {type(e).__name__}: {e}'
            time.sleep(0.5 * a)
            continue
        if r.status_code != 200:
            return {'url': url, 'ok': False, 'error': f'HTTP {r.status_code}'}
        html = r.text
        m = {
            'url': url,
            'ok': True,
            'views': first_int(html, METRIC_PATTERNS['views']),
            'likes': first_int(html, METRIC_PATTERNS['likes']),
            'comments': first_int(html, METRIC_PATTERNS['comments']),
            'time_to_read': first_int(html, METRIC_PATTERNS['time_to_read']),
        }
        return m
    return {'url': url, 'ok': False, 'error': last_err or 'unknown'}


def main():
    with open(ARTICLES_PATH, encoding='utf-8') as f:
        articles = json.load(f)
    print(f'[start] {len(articles)} articles to process')

    sess = make_session()

    results = []
    t0 = time.time()
    ok = fail = 0

    # Последовательно, чтобы не получить капчу/бан
    for i, art in enumerate(articles, 1):
        url = art.get('share_link') or art.get('link')
        if not url:
            fail += 1
            continue
        res = fetch_one(sess, url)
        if res.get('ok'):
            ok += 1
            art_metrics = {k: res.get(k) for k in ('views', 'likes', 'comments', 'time_to_read')}
            art['html_metrics'] = art_metrics
        else:
            fail += 1
            art['html_metrics'] = {'error': res.get('error')}
        results.append(art)
        if i % 10 == 0 or i == len(articles):
            elapsed = time.time() - t0
            rate = i / max(1, elapsed)
            print(f'  [{i}/{len(articles)}] ok={ok} fail={fail} elapsed={elapsed:.1f}s rate={rate:.1f}/s')
        time.sleep(0.5)  # rate limit

    # Сохраняем обогащённый список
    out_path = f'{OUT_DIR}/channel_articles_with_metrics.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    print(f'\n[done] saved to {out_path}')

    # Сводка
    print('\n=== СВОДКА ===')
    print(f'  всего: {len(articles)}')
    print(f'  ok: {ok}, fail: {fail}')
    views = [a['html_metrics'].get('views') for a in articles if a.get('html_metrics', {}).get('views') is not None]
    likes = [a['html_metrics'].get('likes') for a in articles if a.get('html_metrics', {}).get('likes') is not None]
    comments = [a['html_metrics'].get('comments') for a in articles if a.get('html_metrics', {}).get('comments') is not None]
    if views:
        vs = sorted(views)
        print(f'  views:    n={len(vs)} sum={sum(vs)} med={vs[len(vs)//2]} min={vs[0]} max={vs[-1]}')
    if likes:
        ls = sorted(likes)
        print(f'  likes:    n={len(ls)} sum={sum(ls)} med={ls[len(ls)//2]} min={ls[0]} max={ls[-1]}')
    if comments:
        cs = sorted(comments)
        print(f'  comments: n={len(cs)} sum={sum(cs)} med={cs[len(cs)//2]} min={cs[0]} max={cs[-1]}')


if __name__ == '__main__':
    main()
