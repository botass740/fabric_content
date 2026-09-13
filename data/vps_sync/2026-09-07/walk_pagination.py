"""Пройти всю пагинацию канала 'Деньги между строк' и собрать ВСЕ статьи."""
import json
import re
import time
import requests
from pathlib import Path
from collections import Counter

STATE = 'dzen_state.json'
OUT_DIR = 'data/vps_sync/2026-09-07'
CHANNEL_ID = '637b09c7e1c5d415d437e6ab'


def make_session():
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'ru-RU,ru;q=0.9',
        'Referer': 'https://dzen.ru/',
        'X-Requested-With': 'XMLHttpRequest',
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


def main():
    sess = make_session()

    all_items = []
    all_responses = []
    next_url = f'https://dzen.ru/api/v3/launcher/channel'
    params = {'channel_id': CHANNEL_ID, 'limit': 200, 'lang': 'ru'}

    page = 0
    while next_url and page < 30:
        page += 1
        try:
            r = sess.get(next_url, params=params if page == 1 else None, timeout=20)
        except Exception as e:
            print(f'[page {page}] network error: {e}')
            break
        if r.status_code != 200:
            print(f'[page {page}] status={r.status_code} len={len(r.text)}')
            break
        try:
            data = r.json()
        except Exception as e:
            print(f'[page {page}] json error: {e}')
            break
        items = data.get('items', [])
        all_responses.append({
            'page': page,
            'url': r.url,
            'status': r.status_code,
            'n_items': len(items),
            'channel': data.get('channel', {}).get('source', {}).get('title', None),
            'subscribers': data.get('channel', {}).get('source', {}).get('subscribers', None),
        })
        all_items.extend(items)
        print(f'[page {page}] +{len(items)} items, total={len(all_items)}')
        # следующая страница
        more = data.get('more', {})
        next_link = more.get('link') if isinstance(more, dict) else None
        if not next_link:
            print('[done] no more link')
            break
        next_url = next_link
        params = None
        time.sleep(0.5)

    print()
    print(f'=== ИТОГО ===')
    print(f'  страниц пройдено: {page}')
    print(f'  items собрано: {len(all_items)}')

    # Сохраняем
    out = {
        'channel_id': CHANNEL_ID,
        'pages': page,
        'total_items': len(all_items),
        'pages_log': all_responses,
        'channel_meta': all_items[0].get('source') if all_items else None,
    }
    out_path = f'{OUT_DIR}/channel_all_items_meta.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f'  meta: {out_path}')

    # Соберём плоский список: id, title, views, timeToRead, publication_date, link
    rows = []
    for it in all_items:
        rows.append({
            'publication_object_id': it.get('publication_object_id'),
            'title': it.get('title', ''),
            'views': it.get('views'),
            'comments': (it.get('socialInfo') or {}).get('commentCount'),
            'time_to_read_s': it.get('timeToReadSeconds'),
            'publication_date': it.get('publication_date'),
            'creation_time': it.get('creation_time'),
            'link': it.get('link'),
            'share_link': it.get('share_link'),
            'is_promoted': it.get('is_promoted'),
            'is_promo_publication': it.get('is_promo_publication'),
        })
    out_path = f'{OUT_DIR}/channel_all_articles.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f'  articles: {out_path}')

    # Сводка
    print()
    print('=== СВОДКА ПО КАНАЛУ ===')
    src = all_items[0].get('source', {}) if all_items else {}
    print(f'  Название: {src.get("title", "?")}')
    print(f'  Подписчики: {src.get("subscribers", "?")}')
    print(f'  URL: dzen.ru/id/{CHANNEL_ID}')
    total_views = sum((it.get('views') or 0) for it in all_items)
    total_comments = sum(((it.get('socialInfo') or {}).get('commentCount') or 0) for it in all_items)
    print(f'  Всего статей: {len(all_items)}')
    print(f'  Суммарные просмотры: {total_views}')
    print(f'  Суммарные комментарии: {total_comments}')
    if rows:
        vs = sorted([r['views'] for r in rows if r['views'] is not None])
        med = vs[len(vs)//2] if vs else 0
        print(f'  Медиана views: {med}')
        print(f'  Min/Max views: {vs[0] if vs else 0} / {vs[-1] if vs else 0}')
        # топ-10 по views
        top = sorted(rows, key=lambda r: (r['views'] or 0), reverse=True)[:10]
        print('  ТОП-10 по views:')
        for r in top:
            v = r['views'] or 0
            print(f"    {v:6}  {r['title'][:80]}")
    # Метки published_date в %Y-%m-%d
    from datetime import datetime
    from datetime import datetime, timezone
    by_date = Counter()
    for r in rows:
        pd = r.get('publication_date')
        try:
            if pd:
                d = datetime.fromtimestamp(int(pd), tz=timezone.utc).strftime('%Y-%m-%d')
                by_date[d] += 1
        except Exception:
            pass
    print('  Публикации по датам:')
    for d in sorted(by_date.keys()):
        print(f'    {d}: {by_date[d]}')


if __name__ == '__main__':
    main()
