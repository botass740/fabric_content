"""
Simple smoke test for research/storage.py.

Run:  python tools/test_storage.py
"""

import sys
import os
from pathlib import Path

# Ensure the project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.storage import ResearchStorage

DB_PATH = "data/test_research.db"


def main() -> None:
    print("=== ResearchStorage smoke test ===\n")

    # Remove stale DB from previous run
    Path(DB_PATH).unlink(missing_ok=True)

    storage = ResearchStorage(DB_PATH)
    try:
        # ----- Channels -----
        print("1. Upsert channels …")
        ch1 = storage.upsert_channel(
            "fainmanomica",
            url="https://dzen.ru/fainmanomica",
            title="Финансовая грамотность",
            subscribers=120_000,
        )
        ch2 = storage.upsert_channel(
            "investkot",
            url="https://dzen.ru/investkot",
            title="ИнвестКот",
            category="инвестиции",
        )
        print(f"   channel ids: {ch1}, {ch2}")

        # get_channel
        ch = storage.get_channel("fainmanomica")
        assert ch is not None, "get_channel returned None"
        assert ch["title"] == "Финансовая грамотность", f"wrong title: {ch['title']}"
        print(f"   get_channel('fainmanomica') → {ch['title']} ✓")

        # get_all_channels
        all_ch = storage.get_all_channels()
        print(f"   get_all_channels() → {len(all_ch)} channels ✓")

        # update_channel_stats
        storage.update_channel_stats(ch1, 42)
        ch = storage.get_channel("fainmanomica")
        assert ch is not None and ch["articles_count"] == 42
        print(f"   update_channel_stats → articles_count={ch['articles_count']} ✓")

        # ----- Articles -----
        print("\n2. Upsert articles …")
        a1 = storage.upsert_article(
            "amRpKj9oqBJkz0B1",
            channel_id=ch1,
            url="https://dzen.ru/a/amRpKj9oqBJkz0B1",
            title="Как не платить налоги",
            views=5_000,
            likes=120,
        )
        a2 = storage.upsert_article(
            "bBrKkL1prEJsx1C2",
            channel_id=ch1,
            url="https://dzen.ru/a/bBrKkL1prEJsx1C2",
            title="Куда вложить 1000 рублей",
            views=25_000,
            likes=500,
        )
        a3 = storage.upsert_article(
            "cCsLlM2qsFKty2D3",
            channel_id=ch2,
            url="https://dzen.ru/a/cCsLlM2qsFKty2D3",
            title="Лучшие акции 2026",
            views=10_000,
            likes=300,
        )
        print(f"   article ids: {a1}, {a2}, {a3}")

        # Duplicate should return existing id
        a1_dup = storage.upsert_article(
            "amRpKj9oqBJkz0B1",
            channel_id=ch1,
            url="https://dzen.ru/a/amRpKj9oqBJkz0B1",
            title="Changed title",
        )
        assert a1_dup == a1, f"duplicate should return {a1}, got {a1_dup}"
        print(f"   duplicate upsert returns same id ✓")

        # get_article
        art = storage.get_article("amRpKj9oqBJkz0B1")
        assert art is not None and art["title"] == "Как не платить налоги"
        print(f"   get_article → '{art['title']}' ✓")

        # get_unparsed_articles
        unparsed = storage.get_unparsed_articles()
        assert len(unparsed) == 3, f"expected 3 unparsed, got {len(unparsed)}"
        print(f"   get_unparsed_articles() → {len(unparsed)} ✓")

        # mark_as_parsed
        storage.mark_as_parsed(
            a1,
            text="Текст статьи про налоги. Второй абзац.",
            word_count=7,
            paragraphs_count=2,
            headers_count=0,
            has_images=False,
            images_count=0,
        )
        unparsed = storage.get_unparsed_articles()
        assert len(unparsed) == 2, f"expected 2 unparsed, got {len(unparsed)}"
        print(f"   after mark_as_parsed → {len(unparsed)} unparsed left ✓")

        # get_articles_stats
        stats = storage.get_articles_stats()
        print(f"   stats: total={stats['total']}, parsed={stats['parsed']}, "
              f"unparsed={stats['unparsed']}, by_channel={len(stats['by_channel'])} ✓")

        # ----- Crawl sessions -----
        print("\n3. Crawl sessions …")
        sid = storage.start_session()
        print(f"   started session #{sid}")

        storage.finish_session(
            sid,
            channels_count=2,
            articles_found=3,
            articles_new=3,
            errors_count=0,
        )
        print(f"   session #{sid} finished ✓")

        # fail_session
        sid2 = storage.start_session()
        storage.fail_session(sid2, "Network timeout")
        print(f"   session #{sid2} failed ✓")

        # ----- Summary -----
        print("\n4. Summary …")
        summary = storage.get_summary()
        print(f"   channels={summary['channels']}, articles={summary['articles']}, "
              f"parsed={summary['parsed']}")
        if summary["last_crawl"]:
            print(f"   last_crawl: status={summary['last_crawl']['status']}, "
                  f"articles_new={summary['last_crawl']['articles_new']}")
        print("   ✓")

        print("\n=== ALL TESTS PASSED ===")

    finally:
        storage.close()
        # Cleanup
        Path(DB_PATH).unlink(missing_ok=True)
        Path(DB_PATH + "-wal").unlink(missing_ok=True)
        Path(DB_PATH + "-shm").unlink(missing_ok=True)
        print("Cleaned up test database.")


if __name__ == "__main__":
    main()