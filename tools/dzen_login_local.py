"""Локальный вход в Дзен → сохранение storage_state (кроссплатформенно).

Запусти в СВОЁМ терминале (не через бота):
    python tools/dzen_login_local.py

Откроется браузер. Войди в Яндекс/Дзен вручную (логин, SMS, капча).
Убедись, что открывается редактор/профиль Дзена. Затем вернись в терминал
и нажми Enter — состояние (куки + localStorage) сохранится в dzen_state.json.

Этот JSON переносится на VPS (в отличие от папки профиля Chromium, куки
которой зашифрованы ключом ОС и на Linux не расшифруются).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config.settings import get_settings
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "dzen_state.json"
START_URL = "https://dzen.ru/"


def main() -> int:
    # Открываем ТОТ ЖЕ локальный профиль, что использует публикатор —
    # если ты в нём уже залогинен в Дзен, повторный вход не нужен.
    settings = get_settings()
    user_data_dir = str(settings.playwright_user_data_path)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir,
            headless=False,
            slow_mo=50,
            locale="ru-RU",
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(START_URL, timeout=60000)

        print("\n" + "=" * 60)
        print("Войди в Яндекс/Дзен в открывшемся браузере.")
        print("Когда увидишь, что залогинен (профиль/редактор Дзена),")
        print("вернись сюда и нажми Enter.")
        print("=" * 60)
        input("\n>>> Нажми Enter после входа... ")

        context.storage_state(path=str(OUT))
        cookies = context.cookies()
        yandex = [c for c in cookies if "yandex" in c.get("domain", "")]
        dzen = [c for c in cookies if "dzen" in c.get("domain", "")]
        print(f"\nСохранено: {OUT}")
        print(f"Куки всего: {len(cookies)} | yandex: {len(yandex)} | dzen: {len(dzen)}")
        if not yandex and not dzen:
            print("ВНИМАНИЕ: куки Яндекс/Дзен не найдены — вероятно, вход не выполнен.")
        context.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
