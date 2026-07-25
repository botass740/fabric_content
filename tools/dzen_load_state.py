"""VPS: зарядить профиль Playwright куками из dzen_state.json и проверить вход.

Запуск на VPS (под виртуальным дисплеем):
    xvfb-run -a python tools/dzen_load_state.py

Берёт dzen_state.json (перенесённый с локальной машины), открывает профиль
с тем же user_data_dir, что использует публикатор, вручную заливает куки и
localStorage из состояния (launch_persistent_context не принимает storage_state,
поэтому применяем через add_cookies + evaluate), заходит на dzen.ru и проверяет
вход. Куки перешифруются локальным ключом Linux, публикатор их потом прочитает.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config.settings import get_settings
from playwright.sync_api import sync_playwright

STATE = Path(__file__).resolve().parent.parent / "dzen_state.json"


def main() -> int:
    if not STATE.exists():
        print(f"НЕ НАЙДЕН {STATE} — скопируй его с локальной машины.")
        return 1

    state = json.loads(STATE.read_text(encoding="utf-8"))
    cookies = state.get("cookies", [])
    origins = state.get("origins", [])

    settings = get_settings()
    user_data_dir = str(settings.playwright_user_data_path)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir,
            headless=True,
            locale="ru-RU",
            viewport={"width": 1400, "height": 900},
        )
        if cookies:
            context.add_cookies(cookies)
            print(f"Залито куки: {len(cookies)}")

        page = context.pages[0] if context.pages else context.new_page()

        # localStorage применяем по каждому origin: заходим и пишем ключи.
        for origin in origins:
            items = origin.get("localStorage", [])
            if not items:
                continue
            try:
                page.goto(origin["origin"], timeout=30000)
                for it in items:
                    page.evaluate(
                        "([k, v]) => localStorage.setItem(k, v)",
                        [it["name"], it["value"]],
                    )
            except Exception as e:
                print(f"localStorage {origin.get('origin')}: пропущен ({e})")

        page.goto("https://dzen.ru/", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        url = page.url
        prof_cookies = context.cookies()
        yandex = [c for c in prof_cookies if "yandex" in c.get("domain", "")]
        logged_in = "passport" not in url.lower() and "auth" not in url.lower()
        print(f"URL: {url}")
        print(f"Куки в профиле: {len(prof_cookies)} | yandex: {len(yandex)}")
        print("ВХОД ПОДХВАЧЕН" if logged_in and yandex else "ВХОД НЕ ПОДТВЕРДИЛСЯ — проверь состояние")
        context.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
