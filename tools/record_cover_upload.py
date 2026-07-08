import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
import sys
import os

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config.settings import get_settings
from app.config.logging import setup_logging

async def main():
    settings = get_settings()
    setup_logging(settings)
    
    print("=== Запись действий добавления обложки ===")
    print(f"Профиль: {settings.playwright_user_data_dir}")
    
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(settings.playwright_user_data_dir),
            headless=False,
            locale="ru-RU",
            viewport={"width": 1400, "height": 900},
        )
        
        page = context.pages[0] if context.pages else await context.new_page()
        
        # Включаем запись всех кликов и действий
        recorded_actions = []
        
        # Слушаем все клики
        async def on_click(event):
            try:
                element = await page.evaluate("""(x, y) => {
                    const el = document.elementFromPoint(x, y);
                    if (!el) return null;
                    return {
                        tag: el.tagName,
                        id: el.id,
                        className: el.className,
                        type: el.type || '',
                        text: el.innerText?.slice(0, 50) || '',
                        role: el.getAttribute('role') || '',
                        dataTestId: el.getAttribute('data-testid') || '',
                        ariaLabel: el.getAttribute('aria-label') || '',
                        accept: el.getAttribute('accept') || '',
                        outerHTML: el.outerHTML?.slice(0, 200) || ''
                    };
                }""", event.x, event.y)
                
                action = {
                    "type": "click",
                    "x": event.x,
                    "y": event.y,
                    "element": element
                }
                recorded_actions.append(action)
                
                print(f"\n[CLICK] x={event.x:.0f} y={event.y:.0f}")
                if element:
                    print(f"  tag: {element['tag']}")
                    print(f"  id: {element['id']}")
                    print(f"  class: {element['className'][:80]}")
                    print(f"  type: {element['type']}")
                    print(f"  text: {element['text']}")
                    print(f"  role: {element['role']}")
                    print(f"  data-testid: {element['dataTestId']}")
                    print(f"  aria-label: {element['ariaLabel']}")
                    print(f"  accept: {element['accept']}")
                    print(f"  HTML: {element['outerHTML'][:150]}")
                    
            except Exception as e:
                print(f"[CLICK ERROR] {e}")
        
        page.on("click", on_click)
        
        # Слушаем file chooser (появление диалога выбора файла)
        async def on_file_chooser(chooser):
            print(f"\n[FILE CHOOSER OPENED]")
            print(f"  isMultiple: {chooser.is_multiple}")
            element = chooser.element
            try:
                info = await element.evaluate("""el => ({
                    tag: el.tagName,
                    id: el.id,
                    className: el.className,
                    accept: el.accept,
                    name: el.name,
                    outerHTML: el.outerHTML?.slice(0, 300)
                })""")
                print(f"  Элемент: {info}")
                recorded_actions.append({"type": "file_chooser", "element_info": info})
            except Exception as e:
                print(f"  [FILE CHOOSER INFO ERROR] {e}")

            # ДАМП всей страницы: все видимые кнопки и элементы с изображением
            print("\n--- ДАМП СТРАНИЦЫ ПРИ ОТКРЫТИИ FILE CHOOSER ---")
            try:
                dump = await page.evaluate("""
                    () => {
                        const out = {toolbar_items: [], image_related: [], all_buttons: []};

                        // Все элементы с классом содержащим "toolbar" или "Toolbar"
                        document.querySelectorAll('[class*="toolbar"],[class*="Toolbar"]').forEach(el => {
                            if (el.offsetParent !== null) {
                                out.toolbar_items.push({
                                    tag: el.tagName,
                                    cls: el.className.substring(0, 100),
                                    text: (el.innerText || '').trim().substring(0, 30),
                                    childCount: el.children.length
                                });
                            }
                        });

                        // Все элементы с "image" или "Image" в классе
                        document.querySelectorAll('[class*="image"],[class*="Image"]').forEach(el => {
                            if (el.offsetParent !== null) {
                                const r = el.getBoundingClientRect();
                                out.image_related.push({
                                    tag: el.tagName,
                                    cls: el.className.substring(0, 100),
                                    text: (el.innerText || '').trim().substring(0, 30),
                                    rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width)},
                                    role: el.getAttribute('role') || '',
                                    aria: el.getAttribute('aria-label') || ''
                                });
                            }
                        });

                        // Все видимые кнопки с их позицией по Y (отсортировано)
                        document.querySelectorAll('button, [role="button"]').forEach(el => {
                            if (el.offsetParent !== null) {
                                const r = el.getBoundingClientRect();
                                const t = (el.innerText || '').trim().substring(0, 40);
                                out.all_buttons.push({
                                    tag: el.tagName,
                                    text: t,
                                    y: Math.round(r.y),
                                    cls: el.className.substring(0, 60)
                                });
                            }
                        });
                        out.all_buttons.sort((a, b) => a.y - b.y);

                        return out;
                    }
                """)
                print(f"\nТулбар элементы ({len(dump['toolbar_items'])}):")
                for item in dump['toolbar_items']:
                    print(f"  <{item['tag']}> cls={item['cls'][:80]}")
                    print(f"      text='{item['text']}' children={item['childCount']}")

                print(f"\nЭлементы с 'image' ({len(dump['image_related'])}):")
                for item in dump['image_related']:
                    print(f"  <{item['tag']}> cls={item['cls'][:80]}")
                    print(f"      text='{item['text']}' rect={item['rect']}")

                print(f"\nВсе кнопки по Y ({len(dump['all_buttons'])}):")
                for item in dump['all_buttons'][:20]:
                    print(f"  @y={item['y']} <{item['tag']}> '{item['text']}' cls={item['cls'][:50]}")
            except Exception as e:
                print(f"  [DUMP ERROR] {e}")

            # НЕ закрываем диалог — пользователь сам выбирает файл
        
        page.on("filechooser", on_file_chooser)
        
        # Открываем редактор
        print(f"\nОткрываю редактор: https://dzen.ru/editor")        
        await page.goto("https://dzen.ru/editor", wait_until="domcontentloaded")        
        await page.wait_for_timeout(3000)
        
        print("\n" + "="*50)
        print("ИНСТРУКЦИЯ:")
        print("1. Кликни в ПУСТУЮ строку в редакторе")
        print("2. Нажми на появившуюся иконку добавления изображения")
        print("3. Выбери любой файл в диалоге (или закрой диалог)")
        print("4. Все твои действия записываются в консоль")
        print("5. Когда закончишь — нажми Ctrl+C в терминале")
        print("="*50 + "\n")
        
        # Ждем пока пользователь не прервет
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass
        
        print("\n=== Запись завершена ===")
        print(f"Всего действий: {len(recorded_actions)}")
        
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
