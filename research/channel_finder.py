"""
Automatic discovery of Dzen channels relevant to a topic.

Uses Playwright (with stored auth cookies) to search Dzen, extract channel
slugs from search results, and evaluate each channel (subscribers, activity,
relevance).  New channels can be saved directly into the research database.

Usage::

    import asyncio
    from research.channel_finder import ChannelFinder

    async def main():
        finder = ChannelFinder()
        results = await finder.find_and_evaluate()
        saved = finder.save_found_channels(results)
        print(f"Saved {saved} channels")
        finder.close()

    asyncio.run(main())
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research.storage import ResearchStorage

logger = logging.getLogger(__name__)

# Regex for channel slug extraction from URLs
CHANNEL_SLUG_RE = re.compile(r"dzen\.ru/([A-Za-z0-9_.-]+)")
# Regex for article IDs
ARTICLE_URL_RE = re.compile(r"/a/([A-Za-z0-9_-]+)")
# Regex for finding dzen.ru links in text
DZEN_LINK_RE = re.compile(r"(?:https?://)?dzen\.ru/([A-Za-z0-9_.-]+)")
# System paths to skip
SKIP_PATHS = {
    "search", "about", "a", "feed", "subscriptions", "profile", "saved",
    "agency", "articles", "explore", "news", "shorts", "id", "video",
    "channel", "topic", "settings", "notifications", "messages",
    "collections", "bookmarks", "history", "edit", "create",
    "comments", "stats", "media", "upload", "help", "support",
}


class ChannelFinder:
    """Discover, evaluate, and store Dzen channels.

    Args:
        state_path: Path to a Playwright storage-state JSON file.
        db_path: Path to the research SQLite database.
    """

    SEARCH_QUERIES: list[str] = [
        "финансовая грамотность",
        "личные финансы",
        "инвестиции для начинающих",
        "семейный бюджет",
        "как накопить деньги",
        "пассивный доход",
        "куда вложить деньги",
        "экономия денег",
        "финансовая независимость",
        "психология денег",
    ]

    MIN_SUBSCRIBERS: int = 1000
    MAX_DAYS_INACTIVE: int = 90

    FINANCE_KEYWORDS: list[str] = [
        "финанс", "деньг", "инвест", "бюджет", "накопл",
        "доход", "капитал", "экономи", "сбережен", "кредит",
        "ипотек", "вклад", "акци", "облигац", "дивиденд",
    ]

    def __init__(
        self,
        state_path: str = "dzen_state.json",
        db_path: str = "data/research.db",
    ) -> None:
        self._state_path = Path(state_path)
        self._storage = ResearchStorage(db_path)

        logger.info(
            "ChannelFinder initialized (state=%s, db=%s)", state_path, db_path
        )

    # ------------------------------------------------------------------
    # Method 1: Search channels via Dzen search page
    # ------------------------------------------------------------------

    async def search_channels_by_query(
        self,
        query: str,
        max_results: int = 20,
    ) -> list[dict[str, Any]]:
        """Search Dzen for a query and extract channel slugs from results.

        Opens the search results page, collects article links, then extracts
        the author channel slug from each article card.

        Args:
            query: Search query string (e.g. "финансовая грамотность").
            max_results: Max channel slugs to return.

        Returns:
            List of ``{"slug": str, "url": str}`` dicts.
        """
        from playwright.async_api import async_playwright

        from research.channel_crawler import ChannelCrawler

        channel_slugs: set[str] = set()

        search_url = f"https://dzen.ru/search?query={query}"

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    storage_state=str(self._state_path),
                    viewport={"width": 1280, "height": 800},
                )
                page = await context.new_page()

                # Intercept API responses (best-effort)
                search_api_data: list[dict[str, Any]] = []

                async def _on_response(response):
                    try:
                        if any(kw in response.url for kw in ("search", "suggest", "find")):
                            ct = response.headers.get("content-type", "")
                            if "json" in ct:
                                body = await response.json()
                                search_api_data.append({"url": response.url, "body": body})
                    except Exception:
                        pass

                page.on("response", _on_response)

                logger.info("Searching: %s", query)
                await page.goto(search_url, wait_until="networkidle", timeout=30000)
                await asyncio.sleep(2)  # let JS render

                # Scroll a few times to load more results
                for _ in range(3):
                    await page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
                    await asyncio.sleep(1.5)

                # Extract all links on the page
                all_hrefs: list[str] = await page.evaluate(
                    """() => {
                        const links = document.querySelectorAll('a[href]');
                        return Array.from(links).map(a => a.getAttribute('href'));
                    }"""
                )

                # Extract channel slugs from links
                for href in all_hrefs:
                    if not href:
                        continue
                    m = CHANNEL_SLUG_RE.search(href)
                    if m:
                        slug = m.group(1)
                        # Skip system paths and article links
                        first_part = slug.split("/")[0].split("?")[0]
                        if first_part not in SKIP_PATHS and slug not in channel_slugs:
                            channel_slugs.add(slug)

                logger.info(
                    "Search '%s': found %d unique channel slugs",
                    query,
                    len(channel_slugs),
                )

            except Exception as e:
                logger.error("Search error for '%s': %s", query, e)
            finally:
                await browser.close()

        # Build result list (limited to max_results)
        results: list[dict[str, Any]] = []
        for slug in sorted(channel_slugs)[:max_results]:
            results.append({
                "slug": slug,
                "url": f"https://dzen.ru/{slug}",
            })

        return results

    # ------------------------------------------------------------------
    # Method 2: Find channels from already-parsed articles
    # ------------------------------------------------------------------

    async def find_channels_from_articles(self) -> list[dict[str, Any]]:
        """Scan already-parsed articles for mentions of other Dzen channels.

        Searches article texts for ``dzen.ru/SLUG`` patterns.

        Returns:
            List of ``{"slug": str, "url": str, "source_article_id": int}`` dicts.
        """
        articles = self._storage.get_unparsed_articles(limit=500)
        # Also get parsed articles
        import sqlite3

        conn = sqlite3.connect(str(self._storage._db_path))
        conn.row_factory = sqlite3.Row
        try:
            parsed = conn.execute(
                "SELECT id, dzen_id, text, title FROM articles WHERE is_parsed = 1 ORDER BY id DESC LIMIT 500"
            ).fetchall()
        finally:
            conn.close()

        all_articles = list(articles)
        for row in parsed:
            all_articles.append(dict(row))

        found: dict[str, dict[str, Any]] = {}

        for article in all_articles:
            text = (article.get("text") or "") + " " + (article.get("title") or "")
            for m in DZEN_LINK_RE.finditer(text):
                slug = m.group(1)
                first_part = slug.split("/")[0].split("?")[0]
                if first_part in SKIP_PATHS:
                    continue
                # Skip the source article's own channel? We don't know it here,
                # but we'll deduplicate later.
                if slug not in found:
                    found[slug] = {
                        "slug": slug,
                        "url": f"https://dzen.ru/{slug}",
                        "source_article_id": article.get("id"),
                    }

        logger.info("Found %d unique channel mentions in article texts", len(found))
        return list(found.values())

    # ------------------------------------------------------------------
    # Method 3: Evaluate a channel
    # ------------------------------------------------------------------

    async def evaluate_channel(
        self,
        channel_url: str,
        page=None,
    ) -> dict[str, Any] | None:
        """Open a channel page and compute quality metrics.

        Args:
            channel_url: Full Dzen channel URL (e.g. ``https://dzen.ru/vzoprodengi``).
            page: Optional Playwright ``Page`` to reuse.  If ``None``, a new
                  browser is launched and closed automatically.

        Returns:
            Evaluation dict or ``None`` if the channel is unreachable.
        """
        from playwright.async_api import async_playwright

        result: dict[str, Any] = {
            "slug": "",
            "url": channel_url,
            "title": "",
            "description": "",
            "subscribers": 0,
            "subscribers_raw": "?",
            "last_article_date": None,
            "days_inactive": 999,
            "articles_visible": 0,
            "is_finance": False,
            "score": 0,
            "add_to_crawl": False,
        }

        m = CHANNEL_SLUG_RE.search(channel_url)
        result["slug"] = m.group(1) if m else ""

        if page is not None:
            # Reuse a pre-existing page
            return await self._eval_with_page(page, channel_url, result)

        # Own browser
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    storage_state=str(self._state_path),
                    viewport={"width": 1280, "height": 800},
                )
                page = await context.new_page()
                return await self._eval_with_page(page, channel_url, result)
            finally:
                await browser.close()

    async def _eval_with_page(self, page, channel_url: str,
                               result: dict[str, Any]) -> dict[str, Any] | None:
        """Evaluate channel using an already-open Playwright page."""
        try:
            await page.goto(
                channel_url,
                wait_until="networkidle",
                timeout=30000,
            )
            await asyncio.sleep(3)  # let JS render + lazy load

            # ---- Title (from og:title or <title> tag) ----
            try:
                meta = await page.locator('meta[property="og:title"]').get_attribute(
                    "content", timeout=3000
                )
                result["title"] = meta or ""
            except Exception:
                pass
            if not result["title"]:
                try:
                    result["title"] = await page.title()
                except Exception:
                    pass

            # ---- Description ----
            try:
                meta = await page.locator('meta[property="og:description"]').get_attribute(
                    "content", timeout=3000
                )
                result["description"] = meta or ""
            except Exception:
                pass

            # ---- Subscribers: try API data, then page title, then body text ----
            # First, try to extract from the <title> tag (often has "Channel — 12.3K")
            try:
                title_text = await page.title()
                result["subscribers_raw"], result["subscribers"] = \
                    self._extract_subscriber_from_text(title_text)
            except Exception:
                pass

            # Second, try body text (more reliable)
            if result["subscribers"] == 0:
                try:
                    body_text = await page.evaluate(
                        "() => document.body?.innerText || ''"
                    )
                    result["subscribers_raw"], result["subscribers"] = \
                        self._extract_subscriber_from_text(body_text)
                except Exception:
                    pass

            # ---- Date extraction from full body text ----
            try:
                body_text = await page.evaluate(
                    "() => document.body?.innerText || ''"
                )
                dt = self._extract_date_from_text(body_text)
                if dt:
                    result["last_article_date"] = dt.isoformat()[:10]
                    delta = datetime.now(timezone.utc) - dt
                    result["days_inactive"] = max(0, delta.days)
            except Exception:
                pass

            # ---- Try dates from meta description first ----
            if result["description"]:
                dt = self._extract_date_from_text(result["description"])
                if dt:
                    result["last_article_date"] = dt.isoformat()[:10]
                    delta = datetime.now(timezone.utc) - dt
                    result["days_inactive"] = max(0, delta.days)

            # ---- Visible articles + dates ----
            try:
                article_data = await page.evaluate(
                    """() => {
                        const links = document.querySelectorAll('a[href*="/a/"]');
                        const seen = new Set();
                        const results = [];
                        for (const link of links) {
                            const href = link.getAttribute('href');
                            if (!href || seen.has(href)) continue;
                            seen.add(href);
                            // Walk up to find a card container
                            let el = link.parentElement;
                            let depth = 0;
                            while (el && depth < 5) {
                                const text = el.innerText || '';
                                results.push({ href, text: text.slice(0, 300) });
                                break;
                            }
                        }
                        return results;
                    }"""
                )
            except Exception:
                article_data = []

            result["articles_visible"] = len(article_data)

            # Extract dates from card text
            latest_date = None
            for art in article_data:
                text = art.get("text", "")
                dt = self._extract_date_from_text(text)
                if dt and (latest_date is None or dt > latest_date):
                    latest_date = dt

            if latest_date:
                result["last_article_date"] = latest_date.isoformat()[:10]
                delta = datetime.now(timezone.utc) - latest_date
                result["days_inactive"] = max(0, delta.days)

            # ---- Finance relevance ----
            combined = (result["title"] + " " + result["description"]).lower()
            result["is_finance"] = any(
                kw in combined for kw in self.FINANCE_KEYWORDS
            )

            # ---- Score ----
            result["score"] = self._compute_score(result)
            result["add_to_crawl"] = result["score"] >= 40

            logger.info(
                "Evaluated '%s': score=%d, subs=%s, inactive=%dd, finance=%s",
                result["slug"],
                result["score"],
                result.get("subscribers_raw", "?"),
                result["days_inactive"],
                result["is_finance"],
            )

        except Exception as e:
            logger.error("Evaluation error for %s: %s", channel_url, e)
            return None

        return result

    @staticmethod
    def _extract_subscriber_from_text(text: str) -> tuple[str, int]:
        """Find a subscriber count in a page's visible text.

        Handles formats::

            123,6 тыс подписчиков
            123.6K followers
            1 234 читателя

        Returns ``(raw_text, parsed_count)``.
        """
        # Pattern 1: "NUMBER THOUSAND_SIGN subscribers" — may span lines
        pat_sub = r"(\d[\d\s.,]*)\s*(тыс|K|k|M|m|тысяч|миллион)\s*\n?\s*(?:подписчик|читател|follower|subscriber)"
        m = re.search(pat_sub, text, re.IGNORECASE)
        if m:
            raw = m.group(1).strip() + m.group(2).strip()
            return raw, ChannelFinder._parse_subscriber_count(raw)

        # Pattern 2: "subscribers NUMBER" (reverse order)
        pat_rev = r"(?:подписчик|читател|follower|subscriber)(?:ов|а|ей|я|ь)?\s*(\d[\d\s.,]*[KkMm]?)"
        m = re.search(pat_rev, text, re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
            return raw, ChannelFinder._parse_subscriber_count(raw)

        # Pattern 3: "NUMBER K/M" in page text (N > 1000)
        for m in re.finditer(r"(\d[\d\s.,]*[KkMm])", text):
            raw = m.group(1).strip()
            count = ChannelFinder._parse_subscriber_count(raw)
            if 1000 <= count <= 100_000_000:
                return raw, count

        return "?", 0

    # ------------------------------------------------------------------
    # Method 4: Full search + evaluate cycle
    # ------------------------------------------------------------------

    async def find_and_evaluate(
        self,
        queries: list[str] | None = None,
        max_channels: int = 30,
    ) -> list[dict[str, Any]]:
        """Full cycle: search all queries → dedup → evaluate → rank.

        Args:
            queries: List of search queries.  Defaults to ``SEARCH_QUERIES``.
            max_channels: Max channels to return (top-N by score).

        Returns:
            List of evaluation dicts sorted by score descending.
        """
        if queries is None:
            queries = self.SEARCH_QUERIES

        all_slugs: set[str] = set()

        # ---- Step 1: search all queries ----
        for idx, query in enumerate(queries, 1):
            logger.info("[%d/%d] Searching: %s", idx, len(queries), query)
            try:
                channels = await self.search_channels_by_query(query, max_results=20)
                for ch in channels:
                    all_slugs.add(ch["slug"])
                logger.info(
                    "  → %d new slugs (total: %d)",
                    len(channels),
                    len(all_slugs),
                )
            except Exception:
                logger.exception("Search failed for query: %s", query)

            # Pause to avoid spamming Dzen
            if idx < len(queries):
                await asyncio.sleep(2.5)

        logger.info("Total unique slugs found: %d", len(all_slugs))

        # ---- Step 2: exclude known channels ----
        known_channels = self._storage.get_all_channels(active_only=False)
        known_slugs = {c["slug"] for c in known_channels}
        new_slugs = all_slugs - known_slugs

        logger.info(
            "After dedup: %d new slugs (known: %d)",
            len(new_slugs),
            len(known_slugs),
        )

        if not new_slugs:
            logger.info("No new channels to evaluate")
            return []

        # ---- Step 3: evaluate each new channel (shared browser) ----
        evaluated: list[dict[str, Any]] = []

        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    storage_state=str(self._state_path),
                    viewport={"width": 1280, "height": 800},
                )

                for idx, slug in enumerate(sorted(new_slugs), 1):
                    url = f"https://dzen.ru/{slug}"
                    logger.info(
                        "[%d/%d] Evaluating: %s", idx, len(new_slugs), url
                    )

                    try:
                        page = await context.new_page()
                        result = await self.evaluate_channel(url, page=page)
                        await page.close()

                        if result:
                            evaluated.append(result)
                            logger.info(
                                "  -> score=%d, subs=%s",
                                result["score"],
                                result.get("subscribers_raw", "?"),
                            )
                        else:
                            logger.info("  -> skipped (unreachable)")
                    except Exception:
                        logger.exception("Evaluation failed for %s", url)

                    # Pause between evaluations
                    if idx < len(new_slugs):
                        await asyncio.sleep(1.5)

            finally:
                await browser.close()

        # ---- Step 4: sort by score ----
        evaluated.sort(key=lambda x: x.get("score", 0), reverse=True)

        logger.info(
            "Evaluation complete: %d evaluated, returning top %d",
            len(evaluated),
            min(max_channels, len(evaluated)),
        )

        return evaluated[:max_channels]

    # ------------------------------------------------------------------
    # Save to DB
    # ------------------------------------------------------------------

    def save_found_channels(
        self,
        channels: list[dict[str, Any]],
        min_score: int = 40,
    ) -> int:
        """Save evaluated channels with ``score >= min_score`` into the database.

        Args:
            channels: List of evaluation dicts from ``evaluate_channel``.
            min_score: Minimum score threshold.

        Returns:
            Number of channels saved.
        """
        count = 0
        for ch in channels:
            if ch.get("score", 0) >= min_score:
                self._storage.upsert_channel(
                    slug=ch["slug"],
                    url=ch["url"],
                    title=ch.get("title", ""),
                    description=ch.get("description", ""),
                    subscribers=ch.get("subscribers", 0),
                    category="финансы",
                    is_active=ch.get("add_to_crawl", False),
                )
                count += 1
                logger.info(
                    "Saved channel '%s' (score=%d, subs=%s)",
                    ch["slug"],
                    ch["score"],
                    ch.get("subscribers_raw", "?"),
                )

        logger.info("Saved %d/%d channels to DB", count, len(channels))
        return count

    def close(self) -> None:
        """Close the database connection."""
        self._storage.close()
        logger.info("ChannelFinder closed")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_subscriber_count(text: str) -> int:
        """Parse a human-readable subscriber string like '12.3K', '123,6 тыс', '1 234'."""
        text = text.strip().replace(" ", " ").replace(",", ".")

        # Extract number and suffix
        m = re.search(r"([\d\s.]+)\s*(тыс|тысяч|K|k|M|m|миллион|миллиона)?", text)
        if not m:
            return 0
        num_str = m.group(1).replace(" ", "")
        suffix = (m.group(2) or "").lower()
        try:
            num = float(num_str)
        except ValueError:
            return 0
        if suffix in ("k", "тыс", "тысяч"):
            num *= 1_000
        elif suffix in ("m", "миллион", "миллиона"):
            num *= 1_000_000
        return int(num)

    @staticmethod
    def _parse_date_text(text: str) -> datetime | None:
        """Try to parse a date string from a Dzen article card.

        Handles relative dates like "5 мин назад", "вчера", and ISO dates.
        """
        text = text.strip().lower()

        # Relative: "N мин/ч/дн назад"
        rel = re.match(r"(\d+)\s*(мин|ч|дн|день|дня|мес|год)\s*назад", text)
        if rel:
            num = int(rel.group(1))
            unit = rel.group(2)
            now = datetime.now(timezone.utc)
            if unit in ("мин",):
                dt = now - __import__("datetime").timedelta(minutes=num)
            elif unit in ("ч",):
                dt = now - __import__("datetime").timedelta(hours=num)
            elif unit in ("дн", "день", "дня"):
                dt = now - __import__("datetime").timedelta(days=num)
            elif unit in ("мес",):
                dt = now - __import__("datetime").timedelta(days=num * 30)
            elif unit in ("год",):
                dt = now - __import__("datetime").timedelta(days=num * 365)
            else:
                return None
            return dt

        # "вчера"
        if text == "вчера":
            now = datetime.now(timezone.utc)
            return now - __import__("datetime").timedelta(days=1)

        # Try ISO date
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
            try:
                return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue

        return None

    @staticmethod
    def _extract_date_from_text(text: str) -> datetime | None:
        """Extract the most recent date from article card text.

        Scans *text* for relative date patterns (``5 мин назад``, ``вчера``)
        and ISO dates, returning the **most recent** one found.
        """
        now = datetime.now(timezone.utc)
        candidates: list[datetime] = []

        # Relative: "N мин/ч/дн ... назад"
        for m in re.finditer(r"(\d+)\s*(мин|ч|дн|день|дня|час|часов|часа|мес|год)\s*(?:назад|)", text):
            num = int(m.group(1))
            unit = m.group(2)
            if unit in ("мин",):
                candidates.append(now - __import__("datetime").timedelta(minutes=num))
            elif unit in ("ч", "час", "часов", "часа"):
                candidates.append(now - __import__("datetime").timedelta(hours=num))
            elif unit in ("дн", "день", "дня"):
                candidates.append(now - __import__("datetime").timedelta(days=num))
            elif unit in ("мес",):
                candidates.append(now - __import__("datetime").timedelta(days=num * 30))
            elif unit in ("год",):
                candidates.append(now - __import__("datetime").timedelta(days=num * 365))

        # "вчера" / "сегодня"
        if "вчера" in text:
            candidates.append(now - __import__("datetime").timedelta(days=1))
        if "сегодня" in text:
            candidates.append(now)

        # ISO dates
        for m in re.finditer(r"(\d{4})-(\d{2})-(\d{2})", text):
            try:
                candidates.append(
                    datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                             tzinfo=timezone.utc)
                )
            except ValueError:
                continue

        # Russian dates: "20 июля 2025"
        ru_months = {
            "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
            "мая": 5, "июня": 6, "июля": 7, "августа": 8,
            "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
        }
        for month_name, month_num in ru_months.items():
            pattern = rf"(\d{{1,2}})\s*{month_name}\s*(\d{{4}})"
            for m in re.finditer(pattern, text):
                try:
                    candidates.append(
                        datetime(int(m.group(2)), month_num, int(m.group(1)),
                                 tzinfo=timezone.utc)
                    )
                except ValueError:
                    continue

        # Also try "DD.MM.YYYY" and "DD.MM.YY"
        for m in re.finditer(r"(\d{2})\.(\d{2})\.(\d{4}|\d{2})", text):
            try:
                day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
                year = int(year) + (2000 if len(year) == 2 else 0)
                candidates.append(
                    datetime(year, month, day, tzinfo=timezone.utc)
                )
            except ValueError:
                continue

        return max(candidates) if candidates else None

    @staticmethod
    def _compute_score(eval_result: dict[str, Any]) -> int:
        """Compute a quality score (0-100) for a channel."""
        score = 0
        subs = eval_result.get("subscribers", 0)
        days = eval_result.get("days_inactive", 999)
        is_finance = eval_result.get("is_finance", False)
        articles = eval_result.get("articles_visible", 0)

        # Subscribers (max 30)
        if subs >= 100_000:
            score += 30
        elif subs >= 10_000:
            score += 20
        elif subs >= 1_000:
            score += 10

        # Activity (max 40)
        if days < 7:
            score += 40
        elif days < 30:
            score += 30
        elif days < 60:
            score += 15
        elif days < 90:
            score += 5

        # Finance relevance (max 20)
        if is_finance:
            score += 20

        # Content volume (max 10)
        if articles > 20:
            score += 10
        elif articles > 10:
            score += 5
        elif articles > 5:
            score += 2

        return min(score, 100)


def _make_interceptor(result: dict[str, Any]):
    """Create a Playwright response handler that extracts API data."""
    import json as _json

    async def _handler(response):
        try:
            url = response.url
            if any(kw in url for kw in ("search", "suggest", "find", "feed")):
                ct = response.headers.get("content-type", "")
                if "json" in ct:
                    body = await response.json()
                    # Store for potential use
                    if "api_data" not in result:
                        result["api_data"] = []
                    result["api_data"].append({"url": url, "body": body})
        except Exception:
            pass

    return _handler