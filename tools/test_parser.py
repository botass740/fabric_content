"""
Smoke test for research/parser.py — fetch and parse a real Dzen article.

Picks up a test article URL from the command line or falls back to a
hard-coded default.  Requires a valid ``dzen_state.json`` in the project root.

Usage::

    python tools/test_parser.py
    python tools/test_parser.py "https://dzen.ru/a/XXXXXXXX"
"""

import sys
from pathlib import Path

# Ensure the project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.parser import ArticleParser
from bs4 import BeautifulSoup

TEST_ARTICLE_URL = "https://dzen.ru/a/amRpKj9oqBJkz0B1"
STATE_PATH = "dzen_state.json"


def format_number(n: int) -> str:
    """Format an integer with thousand separators for readability."""
    return f"{n:,}".replace(",", " ")


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else TEST_ARTICLE_URL
    print(f"=== ArticleParser test ===\n")
    print(f"URL:        {url}")
    print(f"State file: {STATE_PATH}\n")

    if not Path(STATE_PATH).exists():
        print(f"ERROR: {STATE_PATH} not found — run 'dzen_auth_explorer.py' first to log in.")
        sys.exit(1)

    parser = ArticleParser(STATE_PATH)
    result = parser.parse_article_from_url(url)

    if result is None:
        print("FAILED: could not fetch article (HTTP error or network issue)")
        sys.exit(1)

    # --- Print results ---
    print(f"{'=' * 60}")
    print(f"Title:            {result['title'][:120]}")
    print(f"Text length:      {format_number(result['text_length'])} chars")
    print(f"Word count:       {format_number(result['word_count'])} words")
    print(f"Published at:     {result['published_at'] or '—'}")
    print(f"Images:           {result['images_count']} "
          f"({'has_images' if result['has_images'] else 'no images'})")
    print(f"Paragraphs:       {result['paragraphs_count']}")
    print(f"Headers (h2/h3):  {result['headers_count']}")
    print(f"Dzen ID:          {result['dzen_id']}")
    print(f"{'=' * 60}")

    # First 200 chars of text
    text = result["text"]
    if text:
        preview = text[:200].replace("\n", "\\n")
        print(f"\nText preview (first 200 chars):\n{preview}…")
        print(f"\n{'=' * 60}")
        print("SUCCESS: article parsed correctly")
    else:
        print("\nWARNING: text is empty — diagnostic follows")
        # Fetch raw HTML for debugging
        html = parser.fetch_article(url)
        if html:
            print(f"\nFirst 500 chars of HTML:\n{html[:500]}")
        print(f"\n{'=' * 60}")
        print("PARTIAL: article fetched but text extraction failed")

    # ---- Diagnostic mode: inspect HTML structure ----
    print("\n" + "=" * 60)
    print("DIAGNOSTIC MODE")
    print("=" * 60)

    html = parser.fetch_article(url)
    if html:
        debug_path = "data/debug_article.html"
        Path("data").mkdir(exist_ok=True)
        with open(debug_path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"Полный HTML сохранён: {debug_path} ({len(html)} bytes)")

        soup = BeautifulSoup(html, 'html.parser')

        # Поиск 1: <script type="application/json">
        json_scripts = soup.find_all('script', type='application/json')
        print(f"\nНайдено <script type='application/json'>: {len(json_scripts)}")
        for i, script in enumerate(json_scripts[:3]):  # первые 3
            content = script.string or ""
            print(f"  [{i}] {len(content)} chars, начало: {content[:100]}...")

        # Поиск 2: <script> содержащие window.__
        all_scripts = soup.find_all('script')
        window_scripts = [s for s in all_scripts
                          if s.string and 'window.__' in s.string]
        print(f"\nНайдено <script> с 'window.__': {len(window_scripts)}")
        for i, script in enumerate(window_scripts[:3]):
            content = script.string[:200]
            print(f"  [{i}] начало: {content}...")

        # Поиск 3: data-атрибуты с JSON
        elements_with_data = soup.find_all(attrs={"data-state": True})
        elements_with_data += soup.find_all(attrs={"data-initial-state": True})
        elements_with_data += soup.find_all(attrs={"data-content": True})
        print(f"\nНайдено элементов с data-state/initial-state/content: {len(elements_with_data)}")
        for i, elem in enumerate(elements_with_data[:3]):
            for attr in ['data-state', 'data-initial-state', 'data-content']:
                if elem.get(attr):
                    val = elem[attr][:100]
                    print(f"  [{i}] {elem.name}[{attr}]: {val}...")

        # Поиск 4: количество текстовых блоков
        articles = soup.find_all('article')
        print(f"\nНайдено <article>: {len(articles)}")

        mains = soup.find_all('main')
        print(f"Найдено <main>: {len(mains)}")

        content_divs = soup.find_all('div', class_=lambda c: c and
                                      ('content' in c.lower() or
                                       'article' in c.lower() or
                                       'text' in c.lower()))
        print(f"Найдено <div class=*content/article/text*>: {len(content_divs)}")

        print("\n" + "=" * 60)
        print("RECOMMENDATION:")
        if json_scripts or window_scripts or elements_with_data:
            print("  Найдены встроенные JSON-данные! Нужно модифицировать parser.py для извлечения из JSON")
        else:
            print("  JSON-данных не найдено. Нужен Playwright для рендера страницы")

    sys.exit(0 if text else 1)


if __name__ == "__main__":
    main()