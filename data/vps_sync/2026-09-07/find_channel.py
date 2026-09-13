"""Найти slug нашего канала в Дзене через Playwright + dzen_state.json.

Не выводит значения cookies. Сохраняет скриншот и список URL/якорей,
по которым можно определить slug канала.
"""
import asyncio, json, os
from pathlib import Path
from playwright.async_api import async_playwright

STATE_PATH = 'dzen_state.json'
OUT_DIR = 'data/vps_sync/2026-09-07'
os.makedirs(OUT_DIR, exist_ok=True)


async def main():
    state = json.loads(Path(STATE_PATH).read_text(encoding='utf-8'))

    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            user_data_dir='./playwright_profile',
            headless=False,
            locale='ru-RU',
            viewport={'width': 1400, 'height': 900},
            args=['--disable-blink-features=AutomationControlled'],
        )

        # Применяем cookies (имена и домены — без значений)
        added = 0
        for c in state.get('cookies', []):
            try:
                await browser.add_cookies([{
                    'name': c['name'],
                    'value': c['value'],
                    'domain': c.get('domain', ''),
                    'path': c.get('path', '/'),
                    'secure': c.get('secure', False),
                    'httpOnly': c.get('httpOnly', False),
                    'sameSite': c.get('sameSite', 'Lax'),
                }])
                added += 1
            except Exception:
                pass
        print(f'cookies applied: {added}')

        # localStorage через init script
        init_parts = []
        for o in state.get('origins', []):
            origin = o.get('origin', '')
            if not origin.startswith('http'):
                continue
            for k, v in o.get('localStorage', []):
                vv = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
                # экранируем </script> и перевод строки
                vv = vv.replace('</', '<\\/')
                init_parts.append(
                    f"localStorage.setItem({json.dumps(k)}, {json.dumps(vv)});"
                )
        if init_parts:
            await browser.add_init_script('\n'.join(init_parts))
            print(f'localStorage keys injected from {len(state.get("origins", []))} origins')

        page = await browser.new_page()
        print('=== 1. dzen.ru ===')
        await page.goto('https://dzen.ru/', wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(4000)
        print(f'  url: {page.url}')
        print(f'  title: {await page.title()}')

        # Снимок главной
        await page.screenshot(path=f'{OUT_DIR}/dzen_home.png', full_page=False)
        print(f'  screenshot: {OUT_DIR}/dzen_home.png')

        # Ищу ссылки в HTML: всё что похоже на канал/профиль/редактор
        print()
        print('=== 2. links matching channel/profile/editor/редакт ===')
        links = await page.evaluate("""() => {
            const all = Array.from(document.querySelectorAll('a[href]'));
            return all
                .map(a => ({
                    text: (a.textContent || '').trim().slice(0, 60),
                    href: a.getAttribute('href') || a.href,
                }))
                .filter(x => {
                    const t = (x.text + ' ' + x.href).toLowerCase();
                    return /канал|профиль|profile|редакт|статист|статист|user|publications|me|мой/i.test(t);
                })
                .slice(0, 40);
        }""")
        for l in links:
            print(f"  [{l['text']:40}]  {l['href'][:130]}")

        # Все ссылки, где в URL есть 'id' (id-slug формат Дзена)
        print()
        print('=== 3. ALL hrefs containing /id or profile ===')
        all_links = await page.evaluate("""() => {
            const all = Array.from(document.querySelectorAll('a[href]'));
            return all
                .map(a => a.getAttribute('href') || a.href)
                .filter(h => h.includes('/id') || h.includes('/profile') || h.includes('/editor'))
                .slice(0, 30);
        }""")
        for h in all_links:
            print(f'  {h[:140]}')

        # localStorage на dzen.ru — какие ключи есть после авторизации
        print()
        print('=== 4. localStorage on dzen.ru ===')
        ls = await page.evaluate("""() => {
            const out = {};
            for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i);
                out[k] = (localStorage.getItem(k) || '').slice(0, 100);
            }
            return out;
        }""")
        for k, v in ls.items():
            marker = ' <==' if any(x in k.lower() for x in ['user', 'channel', 'login', 'profile', 'public', 'pub', 'me', 'zen']) else ''
            print(f'  {k}{marker}')
            if marker:
                print(f'      = {v}')

        # zenkookie длина
        zlen = await page.evaluate("""() => {
            const m = document.cookie.match(/(?:^|; )zencookie=([^;]+)/);
            return m ? m[1].length : 0;
        }""")
        print(f'  zencookie length: {zlen}')

        # Попытка зайти на страницу студии
        print()
        print('=== 5. dzen.ru/profile/editor ===')
        try:
            await page.goto('https://dzen.ru/profile/editor', wait_until='domcontentloaded', timeout=30000)
            await page.wait_for_timeout(4000)
            print(f'  url: {page.url}')
            print(f'  title: {await page.title()}')
            await page.screenshot(path=f'{OUT_DIR}/dzen_studio.png', full_page=False)
            # Любые ссылки с id (формат /id/<id>-<slug>/)
            studio_links = await page.evaluate("""() => {
                const all = Array.from(document.querySelectorAll('a[href]'));
                return all
                    .map(a => a.getAttribute('href') || a.href)
                    .filter(h => h.includes('/id/'))
                    .slice(0, 20);
            }""")
            print('  /id/ links:')
            for h in studio_links:
                print(f'    {h[:160]}')
            # Текстовые вхождения со словами "канал", "мой", "статистика"
            text = await page.evaluate("() => document.body.innerText")
            keywords = ['Мой канал', 'Канал', 'Подписчик', 'статистика', 'публикации']
            for kw in keywords:
                if kw in text:
                    # найти фрагмент
                    idx = text.find(kw)
                    print(f'  text contains "{kw}": ...{text[max(0,idx-40):idx+80]}...')
        except Exception as e:
            print(f'  error: {e}')

        # Попытка зайти на статистику
        print()
        print('=== 6. dzen.ru/profile/editor/statistics ===')
        try:
            await page.goto('https://dzen.ru/profile/editor/statistics', wait_until='domcontentloaded', timeout=30000)
            await page.wait_for_timeout(4000)
            print(f'  url: {page.url}')
            print(f'  title: {await page.title()}')
            await page.screenshot(path=f'{OUT_DIR}/dzen_statistics.png', full_page=True)
            # текст
            stat_text = await page.evaluate("() => document.body.innerText.slice(0, 4000)")
            print(f'  stat text (first 4000 chars):\n{stat_text}')
        except Exception as e:
            print(f'  error: {e}')

        await browser.close()


asyncio.run(main())
