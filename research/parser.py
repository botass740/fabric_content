"""
HTML parser for Dzen article pages.

Uses requests + cookies (from Playwright storage state) to fetch and parse
individual Dzen articles.  Does NOT depend on Playwright at runtime — only
the stored cookie file is needed.

Typical usage::

    from research.parser import ArticleParser
    parser = ArticleParser("dzen_state.json")
    result = parser.parse_article_from_url("https://dzen.ru/a/amRpKj9oqBJkz0B1")
    if result:
        print(result["title"], result["text_length"])
"""

import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Referer": "https://dzen.ru/",
}

# Patterns used to find the main content container
CONTENT_CANDIDATE_SELECTORS = [
    "article",
    "[class*='article']",
    "[class*='content']",
    "[class*='publication']",
    "[class*='document']",
    "main",
    "[role='main']",
    "[class*='post']",
    "[class*='text']",
]

# Patterns that mark images to skip (avatars, icons, etc.)
SKIP_IMAGE_PATTERNS = re.compile(
    r"avatar|icon|logo|emoji|sticker|badge|thumb|favicon",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# ArticleParser
# ---------------------------------------------------------------------------


class ArticleParser:
    """Fetch and parse Dzen article pages via HTTP + BeautifulSoup.

    Args:
        state_path: Path to a Playwright storage-state JSON file exported
            via ``browser_context.storage_state()``.  Cookies for
            ``dzen.ru`` / ``yandex.ru`` domains are extracted from it.
    """

    def __init__(self, state_path: str = "dzen_state.json") -> None:
        self._state_path = Path(state_path)
        self._session = requests.Session()
        self._session.headers.update(DEFAULT_HEADERS)

        self._load_cookies(str(self._state_path))

        logger.info(
            "ArticleParser initialized from %s",
            self._state_path,
        )

    # ------------------------------------------------------------------
    # Cookie loading
    # ------------------------------------------------------------------

    def _load_cookies(self, state_path: str) -> None:
        """Load cookies from a Playwright storage-state file into the session.

        Only cookies for ``dzen.ru`` / ``yandex.ru`` domains are kept.
        """
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                state = json.load(f)

            cookies = state.get("cookies", [])
            loaded = 0

            for cookie in cookies:
                domain = cookie.get("domain", "")
                if "dzen.ru" in domain or "yandex.ru" in domain:
                    self._session.cookies.set(
                        name=cookie["name"],
                        value=cookie["value"],
                        domain=cookie.get("domain"),
                        path=cookie.get("path", "/"),
                        secure=cookie.get("secure", False),
                    )
                    loaded += 1

            logger.info("Loaded %d cookies from %s", loaded, state_path)

        except FileNotFoundError:
            logger.error("State file not found: %s", state_path)
            raise
        except Exception as e:
            logger.error("Error loading cookies: %s", e)
            raise

    # ------------------------------------------------------------------
    # Fetching
    # ------------------------------------------------------------------

    def fetch_article(self, url: str) -> str | None:
        """Download an article page and return its HTML, or ``None`` on failure.

        Args:
            url: Full Dzen article URL, e.g. ``https://dzen.ru/a/XXXX``.
        """
        try:
            resp = self._session.get(url, timeout=15)
            if resp.status_code != 200:
                logger.warning(
                    "fetch_article: HTTP %d for %s", resp.status_code, url
                )
                return None
            resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except requests.RequestException:
            logger.exception("fetch_article failed for %s", url)
            return None

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def extract_article_id(url: str) -> str | None:
        """Extract the Dzen article id from a URL.

        >>> ArticleParser.extract_article_id("https://dzen.ru/a/amRpKj9oqBJkz0B1")
        'amRpKj9oqBJkz0B1'
        """
        m = re.search(r"/a/([A-Za-z0-9_-]+)", url)
        return m.group(1) if m else None

    def parse_article(self, html: str, url: str) -> dict[str, Any]:
        """Parse article HTML into a structured dict.

        Tries two strategies in order:
        1. Extract article data from the embedded ``var _params`` JSON.
        2. Fall back to DOM parsing (requests + BeautifulSoup).

        Returns a dict with keys: ``dzen_id``, ``title``, ``text``,
        ``text_length``, ``word_count``, ``published_at``, ``images``,
        ``images_count``, ``has_images``, ``paragraphs_count``,
        ``headers_count``.  Partial results are returned on parse errors.
        """
        result: dict[str, Any] = {
            "dzen_id": self.extract_article_id(url) or "",
            "title": "",
            "text": "",
            "text_length": 0,
            "word_count": 0,
            "published_at": None,
            "images": [],
            "images_count": 0,
            "has_images": False,
            "paragraphs_count": 0,
            "headers_count": 0,
        }

        # ATTEMPT 1: _params JSON path
        params = self._extract_params_json(html)
        if params is not None:
            json_result = self._parse_from_params(params, result)
            if json_result is not None:
                logger.info(
                    "parse_article(%s): parsed from _params JSON "
                    "(%d words, %d paragraphs)",
                    url,
                    json_result["word_count"],
                    json_result["paragraphs_count"],
                )
                return json_result

        # ATTEMPT 2: DOM fallback
        soup = BeautifulSoup(
            html, "html.parser" if "lxml" not in globals() else "lxml"
        )

        try:
            result["title"] = self._extract_title(soup) or ""
            result["published_at"] = self._extract_published_at(soup)

            content_block = self._find_content_block(soup)
            if content_block is not None:
                result["text"] = self._extract_text(content_block)
                result["text_length"] = len(result["text"])
                result["word_count"] = len(result["text"].split())
                result["paragraphs_count"] = len(content_block.find_all("p"))
                result["headers_count"] = len(
                    content_block.find_all(["h2", "h3"])
                )

                images = self._extract_images(content_block)
                result["images"] = images
                result["images_count"] = len(images)
                result["has_images"] = len(images) > 0
            else:
                logger.warning("parse_article(DOM): no content block for %s", url)

            logger.info(
                "parse_article(%s): parsed from DOM "
                "(%d words, %d paragraphs)",
                url,
                result["word_count"],
                result["paragraphs_count"],
            )
        except Exception:
            logger.exception("parse_article(DOM): partial error for %s", url)

        return result

    def _parse_from_params(
        self,
        params: dict[str, Any],
        default_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Try to fill *default_result* from ``_params`` JSON.

        Navigates ``ssrData → publishersResponse → data → data → publication``
        and parses the Draft.js ``contentState``.

        Returns the filled result dict on success, or ``None`` to signal
        the caller should fall back to DOM parsing.
        """
        try:
            publication: dict[str, Any] = (
                params.get("ssrData", {})
                .get("publishersResponse", {})
                .get("data", {})
                .get("data", {})
                .get("publication", {})
            )

            if not publication:
                logger.debug("_parse_from_params: no publication node found")
                return None

            result = dict(default_result)  # shallow copy

            # --- title ---
            # Prefer content.preview.title, fall back to titleForUrl
            content = publication.get("content", {})
            preview = content.get("preview", {})
            result["title"] = preview.get("title", "")
            if not result["title"]:
                result["title"] = publication.get("titleForUrl", "")

            # --- published_at ---
            publish_time = publication.get("publishTime")
            if publish_time:
                from datetime import datetime

                dt = datetime.fromtimestamp(publish_time / 1000)
                result["published_at"] = dt.isoformat()

            # --- article text via Draft.js ---
            article_content = content.get("articleContent", {})
            content_state_str: str = article_content.get("contentState", "")

            if content_state_str:
                draftjs = self._parse_draftjs(content_state_str)
                result["text"] = draftjs["text"]
                result["text_length"] = draftjs["text_length"]
                result["word_count"] = draftjs["word_count"]
                result["paragraphs_count"] = draftjs["paragraphs_count"]
                result["headers_count"] = draftjs["headers_count"]
                result["images"] = draftjs["images"]
                result["images_count"] = len(draftjs["images"])
                result["has_images"] = result["images_count"] > 0

                return result

            logger.debug("_parse_from_params: no contentState string found")
            return None

        except Exception:
            logger.exception("_parse_from_params: error parsing _params JSON")
            return None

    def _extract_params_json(self, html: str) -> dict[str, Any] | None:
        """Find ``var _params =`` inside a ``<script>`` tag and parse the JSON.

        Scans ALL ``<script>`` tags and returns the first ``_params`` that
        parses to a non-empty JSON object (preferring the one that contains
        ``ssrData``, i.e. the article data).

        Handles variants::

            var _params = {JSON};
            var _params=({JSON})
            var _params =  {JSON}

        Returns the parsed dict or ``None``.
        """
        soup = BeautifulSoup(html, "html.parser")
        best: dict[str, Any] | None = None

        for script in soup.find_all("script"):
            text = script.string
            if not text or "var _params" not in text:
                continue

            # Locate the JSON value after '='
            eq_idx = text.find("var _params")
            if eq_idx == -1:
                continue
            eq_idx = text.find("=", eq_idx) + 1
            if eq_idx <= 0:
                continue

            json_str = text[eq_idx:].strip()

            # Strip leading '(' and trailing ');' — the JSON may be wrapped:
            #   var _params=({...})    or    var _params={...};
            if json_str.startswith("("):
                json_str = json_str[1:]

            # Use bracket counting to find the exact JSON object
            obj = self._extract_json_balanced(json_str)
            if obj is None:
                continue

            try:
                parsed = json.loads(obj)
            except json.JSONDecodeError:
                continue

            if not parsed:
                continue

            # Prefer the one with ssrData (article data)
            if "ssrData" in parsed:
                return parsed

            # Keep the first non-empty result as fallback
            if best is None:
                best = parsed

        return best

    @staticmethod
    def _extract_json_balanced(text: str) -> str | None:
        """Extract a balanced JSON object/array starting from the first ``{``.

        Counts braces to handle nested structures, ignoring strings.
        Returns the JSON substring, or ``None`` if no balanced object found.
        """
        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        in_string = False
        escape = False

        for i in range(start, len(text)):
            ch = text[i]

            if escape:
                escape = False
                continue

            if ch == "\\":
                escape = True
                continue

            if ch == '"' and not escape:
                in_string = not in_string
                continue

            if in_string:
                continue

            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]

        return None

    def _parse_draftjs(self, content_state_str: str) -> dict[str, Any]:
        """Parse a Draft.js ``contentState`` JSON string.

        Args:
            content_state_str: The JSON string stored inside the
                ``articleContent.contentState`` field.

        Returns::

            {
                "text":         str,   # all blocks joined by "\\n\\n"
                "text_length":  int,
                "word_count":   int,
                "paragraphs_count": int,
                "headers_count":    int,
                "images":       list[dict],  # see below
            }

        Each image dict::

            {
                "url":      str,
                "alt":      str,
                "position": int,
                "width":    int | None,
                "height":   int | None,
            }
        """
        result: dict[str, Any] = {
            "text": "",
            "text_length": 0,
            "word_count": 0,
            "paragraphs_count": 0,
            "headers_count": 0,
            "images": [],
        }

        try:
            state = json.loads(content_state_str)
        except (json.JSONDecodeError, TypeError):
            logger.warning("_parse_draftjs: contentState is not valid JSON")
            return result

        blocks: list[dict[str, Any]] = (
            state.get("draftJsState", {}).get("blocks", [])
        )
        entity_map: dict[str, Any] = state.get("draftJsState", {}).get(
            "entityMap", {}
        )

        if not blocks:
            return result

        text_parts: list[str] = []
        headers_count = 0
        paragraphs_count = 0
        images: list[dict[str, Any]] = []
        atomic_image_idx = 0

        for block in blocks:
            block_type = block.get("type", "")
            text = block.get("text", "") or ""

            # --- count by type ---
            if block_type in ("header-two", "header-three"):
                headers_count += 1
            elif block_type == "unstyled":
                paragraphs_count += 1

            # --- atomic:image blocks ---
            if block_type == "atomic:image":
                image_id = block.get("data", {}).get("image", {}).get("id")
                if image_id:
                    images.append(
                        {
                            "url": f"image:{image_id}",
                            "alt": "",
                            "position": atomic_image_idx,
                            "width": None,
                            "height": None,
                        }
                    )
                    atomic_image_idx += 1
                continue  # atomic blocks add no text

            # --- collect text ---
            if text.strip():
                text_parts.append(text.strip())

        # --- images from entityMap ---
        for key, entity in entity_map.items():
            if entity.get("type") == "IMAGE":
                data = entity.get("data", {})
                img_url = data.get("src") or data.get("url", "")
                if img_url:
                    images.append(
                        {
                            "url": img_url,
                            "alt": data.get("alt", ""),
                            "position": len(images),
                            "width": data.get("width"),
                            "height": data.get("height"),
                        }
                    )

        # --- assemble result ---
        full_text = "\n\n".join(text_parts)

        result["text"] = full_text
        result["text_length"] = len(full_text)
        result["word_count"] = len(full_text.split())
        result["paragraphs_count"] = paragraphs_count
        result["headers_count"] = headers_count
        result["images"] = images

        return result

    def parse_article_from_url(self, url: str) -> dict[str, Any] | None:
        """Fetch + parse an article in one call.

        Returns:
            Structured dict, or ``None`` if the fetch failed.
        """
        html = self.fetch_article(url)
        if html is None:
            return None
        return self.parse_article(html, url)

    # ------------------------------------------------------------------
    # Internal extractors
    # ------------------------------------------------------------------

    def _extract_title(self, soup: BeautifulSoup) -> str | None:
        """Extract article title, trying multiple sources in priority order."""
        # 1. <h1> any class
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            return h1.get_text(strip=True)

        # 2. og:title
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content", "").strip():
            return og_title["content"].strip()

        # 3. <title> tag, strip " — Дзен" suffix
        title_tag = soup.find("title")
        if title_tag and title_tag.get_text(strip=True):
            raw = title_tag.get_text(strip=True)
            raw = re.sub(r"\s*[—–-]\s*Дзен.*$", "", raw).strip()
            return raw

        return None

    def _extract_published_at(self, soup: BeautifulSoup) -> str | None:
        """Extract publication date as ISO string."""
        # <time datetime="...">
        time_el = soup.find("time")
        if time_el and time_el.get("datetime"):
            return time_el["datetime"]

        # meta[property="article:published_time"]
        meta_pub = soup.find("meta", property="article:published_time")
        if meta_pub and meta_pub.get("content"):
            return meta_pub["content"]

        return None

    def _find_content_block(self, soup: BeautifulSoup) -> Tag | None:
        """Heuristic: find the element with the most text among candidates."""
        best: Tag | None = None
        best_len = 0

        for selector in CONTENT_CANDIDATE_SELECTORS:
            for candidate in soup.select(selector):
                text_len = len(candidate.get_text(strip=True))
                if text_len > best_len:
                    best_len = text_len
                    best = candidate

        return best

    def _extract_text(self, container: Tag) -> str:
        """Extract clean text from a content container.

        Removes ``<script>`` and ``<style>`` tags, then joins text blocks
        with double newlines (paragraph breaks).
        """
        # Remove scripts and styles
        for tag in container.find_all(["script", "style", "noscript"]):
            tag.decompose()

        # Collect paragraph-level text blocks
        blocks: list[str] = []
        for el in container.find_all(
            ["p", "h2", "h3", "h4", "blockquote", "li", "pre"]
        ):
            text = el.get_text(strip=True)
            if text:
                blocks.append(text)

        # If no structured blocks found, fall back to full text
        if not blocks:
            full = container.get_text(separator="\n", strip=True)
            blocks.append(full)

        return "\n\n".join(blocks)

    def _extract_images(self, container: Tag) -> list[dict[str, Any]]:
        """Extract content images, skipping avatars/icons.

        Returns:
            List of ``{"url": str, "alt": str, "position": int}``.
        """
        images: list[dict[str, Any]] = []
        for idx, img in enumerate(container.find_all("img")):
            src = img.get("src") or img.get("data-src") or ""
            if not src:
                continue

            # Skip avatars, icons, logos
            if SKIP_IMAGE_PATTERNS.search(src):
                continue

            # Skip if width/height attributes suggest tiny icon
            w = self._parse_dimension(img.get("width"))
            h = self._parse_dimension(img.get("height"))
            if w is not None and h is not None and (w < 100 or h < 100):
                continue

            images.append(
                {
                    "url": src,
                    "alt": img.get("alt", ""),
                    "position": idx,
                }
            )
        return images

    @staticmethod
    def _parse_dimension(value: Any) -> int | None:
        """Parse a dimension string/number to int, or None."""
        if value is None:
            return None
        try:
            return int(str(value).replace("px", "").strip())
        except (ValueError, TypeError):
            return None