"""
Playwright-based crawler for Dzen channel pages.

Opens a channel page with stored auth cookies, scrolls to collect article
URLs, and optionally extracts channel metadata.  Uses ``asyncio`` + Playwright.

Typical usage::

    import asyncio
    from research.channel_crawler import ChannelCrawler

    async def main():
        crawler = ChannelCrawler("dzen_state.json")
        urls = await crawler.get_article_urls("https://dzen.ru/fainmanomica")
        info = await crawler.get_channel_info("https://dzen.ru/fainmanomica")
        print(info, len(urls))

    asyncio.run(main())
"""

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Regex for article links: /a/XXXXXX
ARTICLE_URL_RE = re.compile(r"/a/([A-Za-z0-9_-]+)")


class ChannelCrawler:
    """Collect article URLs and channel metadata from a Dzen channel page.

    Uses Playwright (Chromium, headless) with stored authentication cookies.

    Args:
        state_path: Path to a Playwright storage-state JSON file.
    """

    def __init__(self, state_path: str = "dzen_state.json") -> None:
        self._state_path = Path(state_path)
        if not self._state_path.exists():
            logger.warning(
                "ChannelCrawler: state file not found: %s", self._state_path
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_article_urls(
        self,
        channel_url: str,
        max_articles: int = 50,
        scroll_pause: float = 2.0,
    ) -> list[str]:
        """Open a channel page, scroll to collect article URLs.

        Args:
            channel_url: Dzen channel URL, e.g. ``https://dzen.ru/fainmanomica``.
            max_articles: Stop scrolling once this many unique URLs are found.
            scroll_pause: Seconds to wait after each scroll (for content to load).

        Returns:
            List of full article URLs like ``https://dzen.ru/a/XXXX``.
        """
        from playwright.async_api import async_playwright

        collected: set[str] = set()
        empty_scrolls = 0

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                storage_state=str(self._state_path),
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()

            # --- network interception (best-effort) ---
            api_responses: list[dict[str, Any]] = []

            async def _on_response(response):
                try:
                    url = response.url
                    if any(kw in url for kw in ("/api/", "feed", "articles")):
                        ct = response.headers.get("content-type", "")
                        if "json" in ct:
                            body = await response.json()
                            api_responses.append({"url": url, "body": body})
                except Exception:
                    pass  # non-critical

            page.on("response", _on_response)

            try:
                # --- open channel page ---
                logger.info("Opening channel: %s", channel_url)
                await page.goto(channel_url, wait_until="networkidle", timeout=30000)

                # Initial collection from HTML
                new_urls = await self._collect_article_links(page)
                collected.update(new_urls)
                logger.info(
                    "After initial load: %d unique articles (target: %d)",
                    len(collected),
                    max_articles,
                )

                # --- scroll loop ---
                while len(collected) < max_articles:
                    prev_count = len(collected)

                    await page.evaluate(
                        "window.scrollBy(0, window.innerHeight * 2)"
                    )
                    await asyncio.sleep(scroll_pause)

                    new_urls = await self._collect_article_links(page)
                    collected.update(new_urls)

                    new_count = len(collected) - prev_count
                    if new_count == 0:
                        empty_scrolls += 1
                        logger.debug(
                            "No new articles this scroll (%d/%d empty)",
                            empty_scrolls,
                            3,
                        )
                    else:
                        empty_scrolls = 0
                        logger.info(
                            "Scroll: +%d articles → %d total",
                            new_count,
                            len(collected),
                        )

                    if empty_scrolls >= 3:
                        logger.info("Stopping: 3 empty scrolls in a row")
                        break

            finally:
                await browser.close()

        # Log any API data we intercepted (useful for debugging)
        if api_responses:
            logger.debug(
                "Intercepted %d API responses during crawl", len(api_responses)
            )

        # Build full URLs
        result = sorted(
            f"https://dzen.ru/a/{aid}" for aid in collected
        )
        logger.info(
            "Channel crawl done: %d unique article URLs from %s",
            len(result),
            channel_url,
        )
        return result

    async def get_channel_info(self, channel_url: str) -> dict[str, Any]:
        """Extract channel metadata: title, description, subscriber count.

        Args:
            channel_url: Dzen channel URL.

        Returns:
            Dict with keys: ``title``, ``description``, ``subscribers``, ``url``.
        """
        from playwright.async_api import async_playwright

        result: dict[str, Any] = {
            "title": "",
            "description": "",
            "subscribers": None,
            "url": channel_url,
        }

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    storage_state=str(self._state_path),
                    viewport={"width": 1280, "height": 800},
                )
                page = await context.new_page()

                await page.goto(
                    channel_url,
                    wait_until="domcontentloaded",
                    timeout=30000,
                )

                # Title from og:title meta tag
                try:
                    title = await page.locator(
                        'meta[property="og:title"]'
                    ).get_attribute("content", timeout=3000)
                    result["title"] = title or ""
                except Exception:
                    pass

                # Description from og:description meta tag
                try:
                    desc = await page.locator(
                        'meta[property="og:description"]'
                    ).get_attribute("content", timeout=3000)
                    result["description"] = desc or ""
                except Exception:
                    pass

                # Subscriber count — try multiple selectors
                subscribers_selectors = [
                    '[class*="subscribers"]',
                    '[class*="followers"]',
                    '[class*="Subscribers"]',
                    '[class*="counter"]',
                    '[class*="subs-count"]',
                    '[class*="count"]',
                ]
                for selector in subscribers_selectors:
                    try:
                        el = page.locator(selector).first
                        text = await el.text_content(timeout=2000)
                        if text and text.strip():
                            result["subscribers"] = self._parse_subscriber_count(
                                text.strip()
                            )
                            break
                    except Exception:
                        continue

                logger.info(
                    "Channel info: '%s', subscribers: %s",
                    result["title"],
                    result["subscribers"],
                )

            except Exception as e:
                logger.error("get_channel_info error: %s", e)
            finally:
                await browser.close()

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _collect_article_links(self, page) -> set[str]:
        """Extract unique article ids from ``<a href="/a/...">`` on the page."""
        hrefs = await page.evaluate(
            """() => {
                const links = document.querySelectorAll('a[href*="/a/"]');
                return Array.from(links).map(a => a.getAttribute('href'));
            }"""
        )

        ids: set[str] = set()
        for href in hrefs:
            if href:
                m = ARTICLE_URL_RE.search(href)
                if m:
                    ids.add(m.group(1))
        return ids

    @staticmethod
    def _parse_subscriber_count(text: str) -> int:
        """Parse a human-readable subscriber string like '12.3K' or '1 234'."""
        text = text.strip().replace(" ", " ").replace(",", ".")
        # Remove non-numeric chars except dots and K/M
        m = re.search(r"([\d\s.]+)\s*([KkMm]?)", text)
        if not m:
            return 0
        num_str = m.group(1).replace(" ", "")
        suffix = m.group(2).lower()
        try:
            num = float(num_str)
        except ValueError:
            return 0
        if suffix == "k":
            num *= 1_000
        elif suffix == "m":
            num *= 1_000_000
        return int(num)