"""
Main crawler orchestrator for Dzen research.

Combines Playwright-based channel crawling (``ChannelCrawler``) with
requests-based article parsing (``ArticleParser``) and SQLite storage
(``ResearchStorage``).

Usage::

    import asyncio
    from research.crawler import ResearchCrawler

    async def main():
        crawler = ResearchCrawler()
        result = await crawler.crawl_channel("https://dzen.ru/igorfaynman")
        print(result)
        crawler.close()

    asyncio.run(main())
"""

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Any

from research.channel_crawler import ChannelCrawler
from research.parser import ArticleParser
from research.storage import ResearchStorage

logger = logging.getLogger(__name__)

# Regex to extract the slug from a channel URL like https://dzen.ru/igorfaynman
SLUG_RE = re.compile(r"dzen\.ru/([A-Za-z0-9_.-]+)")


class ResearchCrawler:
    """High-level orchestrator that coordinates crawling, parsing, and storage.

    Args:
        state_path: Path to a Playwright storage-state JSON file.
        db_path: Path to the research SQLite database.
    """

    def __init__(
        self,
        state_path: str = "dzen_state.json",
        db_path: str = "data/research.db",
    ) -> None:
        self._state_path = state_path
        self._channel_crawler = ChannelCrawler(state_path)
        self._article_parser = ArticleParser(state_path)
        self._storage = ResearchStorage(db_path)

        logger.info(
            "ResearchCrawler initialized (state=%s, db=%s)", state_path, db_path
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def crawl_channel(
        self,
        channel_url: str,
        max_articles: int = 50,
    ) -> dict[str, Any]:
        """Crawl a single Dzen channel — collect URLs, parse articles, save to DB.

        Args:
            channel_url: Full channel URL, e.g. ``https://dzen.ru/igorfaynman``.
            max_articles: Maximum number of articles to collect from the channel.

        Returns:
            Stats dict with keys: ``channel``, ``articles_found``,
            ``articles_new``, ``articles_skipped``, ``errors``.
        """
        slug = self._extract_slug(channel_url)
        if not slug:
            logger.error("Cannot extract slug from URL: %s", channel_url)
            return {
                "channel": channel_url,
                "articles_found": 0,
                "articles_new": 0,
                "articles_skipped": 0,
                "errors": 1,
            }

        logger.info(
            "Crawling channel '%s' (slug=%s, max_articles=%d)",
            channel_url,
            slug,
            max_articles,
        )

        # --- ensure channel exists in DB ---
        channel_id = self._storage.upsert_channel(slug, url=channel_url)
        logger.debug("Channel DB id=%s for slug='%s'", channel_id, slug)

        # --- get channel info via Playwright ---
        try:
            channel_info = await self._channel_crawler.get_channel_info(channel_url)
            self._storage.upsert_channel(
                slug,
                url=channel_url,
                title=channel_info.get("title", ""),
                description=channel_info.get("description", ""),
                subscribers=channel_info.get("subscribers", 0),
            )
            logger.info(
                "Channel info: '%s' — %s subscribers",
                channel_info.get("title", ""),
                channel_info.get("subscribers", "?"),
            )
        except Exception:
            logger.exception("Failed to get channel info for %s", channel_url)
            # Continue anyway — we can still collect articles

        # --- collect article URLs ---
        try:
            article_urls = await self._channel_crawler.get_article_urls(
                channel_url,
                max_articles=max_articles,
            )
        except Exception:
            logger.exception("Failed to collect article URLs for %s", channel_url)
            return {
                "channel": channel_url,
                "articles_found": 0,
                "articles_new": 0,
                "articles_skipped": 0,
                "errors": 1,
            }

        articles_found = len(article_urls)
        articles_new = 0
        articles_skipped = 0
        errors = 0

        logger.info(
            "Collected %d article URLs from '%s' — starting parse loop",
            articles_found,
            slug,
        )

        # --- parse each article ---
        loop = asyncio.get_event_loop()

        for idx, url in enumerate(article_urls, 1):
            dzen_id = ArticleParser.extract_article_id(url)
            if not dzen_id:
                logger.warning("Cannot extract dzen_id from URL: %s", url)
                errors += 1
                continue

            # Check if already parsed
            existing = self._storage.get_article(dzen_id)
            if existing and existing.get("is_parsed"):
                articles_skipped += 1
                logger.debug(
                    "[%d/%d] Skipping already-parsed article '%s'",
                    idx,
                    articles_found,
                    dzen_id,
                )
                continue

            # Parse the article (synchronous — run in thread pool)
            try:
                result = await loop.run_in_executor(
                    None,
                    self._article_parser.parse_article_from_url,
                    url,
                )
            except Exception:
                logger.exception("[%d/%d] Parse error for %s", idx, articles_found, url)
                errors += 1
                continue

            if result is None:
                logger.warning(
                    "[%d/%d] Failed to fetch article %s", idx, articles_found, url
                )
                errors += 1
                continue

            # Save to DB
            try:
                article_id = self._storage.upsert_article(
                    dzen_id,
                    channel_id=channel_id,
                    url=url,
                    title=result.get("title", ""),
                    published_at=result.get("published_at"),
                    text_length=result.get("text_length", 0),
                    word_count=result.get("word_count", 0),
                    has_images=result.get("has_images", False),
                    images_count=result.get("images_count", 0),
                )

                self._storage.mark_as_parsed(
                    article_id,
                    text=result.get("text", ""),
                    word_count=result.get("word_count", 0),
                    paragraphs_count=result.get("paragraphs_count", 0),
                    headers_count=result.get("headers_count", 0),
                    has_images=result.get("has_images", False),
                    images_count=result.get("images_count", 0),
                )

                articles_new += 1
                logger.info(
                    "[%d/%d] Parsed: '%s' (%d words) — %s",
                    idx,
                    articles_found,
                    dzen_id,
                    result.get("word_count", 0),
                    result.get("title", "")[:60],
                )

            except Exception:
                logger.exception(
                    "[%d/%d] DB save error for %s", idx, articles_found, dzen_id
                )
                errors += 1
                continue

        # --- update channel stats (total articles in DB, not just new) ---
        self._storage.update_channel_stats(channel_id, articles_found)

        stats = {
            "channel": channel_url,
            "articles_found": articles_found,
            "articles_new": articles_new,
            "articles_skipped": articles_skipped,
            "errors": errors,
        }

        logger.info(
            "Crawl finished for '%s': found=%d, new=%d, skipped=%d, errors=%d",
            slug,
            articles_found,
            articles_new,
            articles_skipped,
            errors,
        )
        return stats

    async def crawl_from_seed(
        self,
        seed_file: str = "tools/dzen_channels_seed.txt",
        max_articles_per_channel: int = 50,
    ) -> dict[str, Any]:
        """Crawl all channels listed in a seed file.

        Each line is a channel URL.  Lines starting with ``#`` and blank lines
        are ignored.

        Args:
            seed_file: Path to the seed file.
            max_articles_per_channel: Max articles per channel.

        Returns:
            Aggregated stats dict with keys: ``channels_count``,
            ``articles_found``, ``articles_new``, ``errors``.
        """
        seed_path = Path(seed_file)
        if not seed_path.exists():
            logger.error("Seed file not found: %s", seed_file)
            return {"channels_count": 0, "articles_found": 0, "articles_new": 0, "errors": 1}

        # Read URLs from seed file
        channel_urls: list[str] = []
        with open(seed_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Basic validation — must be a dzen.ru URL
                if "dzen.ru/" in line:
                    channel_urls.append(line)
                else:
                    logger.warning("Skipping invalid seed line: %s", line)

        if not channel_urls:
            logger.warning("No valid channel URLs found in %s", seed_file)
            return {"channels_count": 0, "articles_found": 0, "articles_new": 0, "errors": 0}

        logger.info(
            "Starting seed crawl: %d channels, %d articles/channel",
            len(channel_urls),
            max_articles_per_channel,
        )

        # Create crawl session
        session_id = self._storage.start_session()

        total_found = 0
        total_new = 0
        total_errors = 0
        channels_processed = 0

        for idx, channel_url in enumerate(channel_urls, 1):
            logger.info(
                "\n--- [%d/%d] Crawling channel: %s ---",
                idx,
                len(channel_urls),
                channel_url,
            )

            try:
                stats = await self.crawl_channel(
                    channel_url,
                    max_articles=max_articles_per_channel,
                )
                channels_processed += 1
                total_found += stats["articles_found"]
                total_new += stats["articles_new"]
                total_errors += stats["errors"]

                logger.info(
                    "[%d/%d] Done: %s — found=%d, new=%d, errors=%d",
                    idx,
                    len(channel_urls),
                    channel_url,
                    stats["articles_found"],
                    stats["articles_new"],
                    stats["errors"],
                )
            except Exception:
                logger.exception(
                    "[%d/%d] Unhandled error crawling %s",
                    idx,
                    len(channel_urls),
                    channel_url,
                )
                total_errors += 1
                continue

        # Finish session
        self._storage.finish_session(
            session_id,
            channels_count=channels_processed,
            articles_found=total_found,
            articles_new=total_new,
            errors_count=total_errors,
        )

        aggregate = {
            "channels_count": channels_processed,
            "articles_found": total_found,
            "articles_new": total_new,
            "errors": total_errors,
        }

        logger.info(
            "Seed crawl complete: %d channels, %d articles, %d errors",
            channels_processed,
            total_new,
            total_errors,
        )
        return aggregate

    def close(self) -> None:
        """Close the database connection."""
        self._storage.close()
        logger.info("ResearchCrawler closed")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_slug(channel_url: str) -> str | None:
        """Extract the channel slug from a Dzen URL.

        >>> ResearchCrawler._extract_slug("https://dzen.ru/igorfaynman")
        'igorfaynman'
        """
        m = SLUG_RE.search(channel_url)
        return m.group(1) if m else None