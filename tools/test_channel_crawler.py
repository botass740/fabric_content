"""
Smoke test for ``research/channel_crawler.py`` — collect article URLs and
channel metadata from a real Dzen channel.

Usage::

    python tools/test_channel_crawler.py
"""

import asyncio
import sys
from pathlib import Path

# Ensure the project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.channel_crawler import ChannelCrawler

TEST_CHANNEL_URL = "https://dzen.ru/igorfaynman"
STATE_PATH = "dzen_state.json"
MAX_ARTICLES = 20


async def main() -> None:
    print("=" * 60)
    print("ChannelCrawler Test")
    print("=" * 60)
    print(f"Channel: {TEST_CHANNEL_URL}")
    print(f"Max articles: {MAX_ARTICLES}")
    print()

    if not Path(STATE_PATH).exists():
        print(f"ERROR: {STATE_PATH} not found — run dzen_auth_explorer.py first.")
        sys.exit(1)

    crawler = ChannelCrawler(STATE_PATH)

    # ---- Test 1: channel info ----
    print("Getting channel info...")
    channel_info = await crawler.get_channel_info(TEST_CHANNEL_URL)
    print(f"\nChannel info:")
    print(f"  Title:       {channel_info.get('title', '--')}")
    print(f"  Description: {channel_info.get('description', '--')[:100]}...")
    print(f"  Subscribers: {channel_info.get('subscribers', '--')}")
    print()

    # ---- Test 2: article URLs ----
    print(f"Collecting article URLs (max {MAX_ARTICLES})...")
    article_urls = await crawler.get_article_urls(
        TEST_CHANNEL_URL,
        max_articles=MAX_ARTICLES,
        scroll_pause=2.0,
    )

    print(f"\n{'=' * 60}")
    print(f"Articles found: {len(article_urls)}")
    print(f"{'=' * 60}")

    if article_urls:
        print("\nFirst 5 URLs:")
        for i, url in enumerate(article_urls[:5], 1):
            print(f"  {i}. {url}")

        # Validate format
        valid = all("/a/" in url for url in article_urls)
        unique = len(article_urls) == len(set(article_urls))

        print(f"\nValidation:")
        print(f"  All URLs contain /a/: {'YES' if valid else 'NO'}")
        print(f"  All URLs are unique:   {'YES' if unique else 'NO'}")

        if valid and unique:
            print(f"\n{'=' * 60}")
            print("SUCCESS: ChannelCrawler works correctly")
            print(f"{'=' * 60}")
        else:
            print("\nWARNING: URL format issues detected")
    else:
        print("\nERROR: no articles found")
        print("Possible causes:")
        print("  - Channel page did not load")
        print("  - Link selectors are wrong")
        print("  - Auth required (check dzen_state.json)")


if __name__ == "__main__":
    asyncio.run(main())