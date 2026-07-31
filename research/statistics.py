"""
Statistical analysis of the Dzen article corpus.

Provides full-text, structural, and temporal analysis of articles collected
from Dzen channels.  Uses only the Python standard library — no numpy,
pandas, or sklearn.

Usage::

    from research.statistics import ArticleStatistics

    stats = ArticleStatistics()
    result = stats.run_full_analysis()
    stats.close()
    print(result["corpus"]["total_articles"])
"""

import json
import logging
import re
import sqlite3
import statistics
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STOP_WORDS: set[str] = {
    "и", "в", "на", "с", "по", "к", "из", "от", "до", "за",
    "не", "но", "а", "что", "как", "это", "так", "же", "уже",
    "еще", "ещё", "или", "то", "он", "она", "они", "мы", "вы",
    "я", "его", "её", "их", "нас", "вам", "для", "при", "об",
    "под", "над", "без", "через", "после", "во", "со", "о",
    "бы", "ли", "если", "когда", "чем", "всё", "все", "был",
    "была", "были", "есть", "нет", "можно", "надо", "нужно",
    "этот", "эта", "эти", "свой", "своя", "свои", "году",
    "лет", "года", "тыс", "млн", "тысяч", "рублей", "рубль",
}

# Punctuation to strip from tokens
PUNCT_RE = re.compile(r"[!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~«»]")

# Title pattern regexes
TITLE_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    ("number_list", r"^\d+\s", re.compile(r"^\d+\s")),
    ("how_to", r"^[Кк]ак\s", re.compile(r"^[Кк]ак\s")),
    ("quote", r"^[«\"'']", re.compile(r"^[«\"'']")),
    ("question", r"\?$", re.compile(r"\?$")),
    ("colon_split", r":\s", re.compile(r":\s")),
    ("money_amount", r"\d+\s*(?:тыс|млн|тысяч|миллион|рубл|₽)", re.compile(r"\d+\s*(?:тыс|млн|тысяч|миллион|рубл|₽)")),
    ("age_mention", r"\d+\s*лет", re.compile(r"\d+\s*лет")),
]

PERSONAL_WORDS: set[str] = {
    "дед", "бабушк", "мать", "отец", "сын", "дочь",
    "внук", "тёт", "дядь", "муж", "жен", "сосед",
    "подруг", "друг", "знаком", "коллег",
}


class ArticleStatistics:
    """Full statistical analysis of the Dzen article corpus.

    Args:
        db_path: Path to the research SQLite database.
    """

    def __init__(self, db_path: str = "data/research.db") -> None:
        self._db_path = Path(db_path)
        self._conn = sqlite3.connect(
            f"file:{self._db_path.resolve()}?mode=ro",
            uri=True,
        )
        self._conn.row_factory = sqlite3.Row
        logger.info("ArticleStatistics opened (read-only): %s", self._db_path)

    # ------------------------------------------------------------------
    # Block 1: Text length statistics
    # ------------------------------------------------------------------

    def text_length_stats(self) -> dict[str, Any]:
        """Analyse article word-count distribution.

        Returns:
            Dict with mean, median, std, min, max, percentiles,
            distribution buckets, and per-channel breakdown.
        """
        rows = self._conn.execute(
            "SELECT word_count, slug FROM articles "
            "JOIN channels ON channels.id = articles.channel_id "
            "WHERE is_parsed = 1 AND word_count > 0"
        ).fetchall()

        word_counts: list[int] = []
        by_channel: dict[str, list[int]] = {}

        for r in rows:
            wc = r["word_count"]
            slug = r["slug"]
            word_counts.append(wc)
            by_channel.setdefault(slug, []).append(wc)

        if not word_counts:
            return self._empty_text_stats()

        word_counts.sort()
        n = len(word_counts)
        total = sum(word_counts)
        mean = total / n
        median = statistics.median(word_counts)
        try:
            std = statistics.stdev(word_counts) if n > 1 else 0.0
        except statistics.StatisticsError:
            std = 0.0

        distribution = self._bucket_distribution(
            word_counts, [200, 400, 600, 800, 1000]
        )

        by_channel_stats: dict[str, dict[str, Any]] = {}
        for slug, counts in by_channel.items():
            if counts:
                counts.sort()
                by_channel_stats[slug] = {
                    "mean": round(sum(counts) / len(counts), 1),
                    "median": statistics.median(counts),
                    "count": len(counts),
                }

        return {
            "total_articles": n,
            "mean_words": round(mean, 1),
            "median_words": median,
            "std_words": round(std, 1),
            "min_words": word_counts[0],
            "max_words": word_counts[-1],
            "percentile_25": word_counts[int(n * 0.25)],
            "percentile_75": word_counts[int(n * 0.75)],
            "distribution": distribution,
            "by_channel": by_channel_stats,
        }

    def _empty_text_stats(self) -> dict[str, Any]:
        return {
            "total_articles": 0,
            "mean_words": 0.0,
            "median_words": 0,
            "std_words": 0.0,
            "min_words": 0,
            "max_words": 0,
            "percentile_25": 0,
            "percentile_75": 0,
            "distribution": {},
            "by_channel": {},
        }

    # ------------------------------------------------------------------
    # Block 2: Title statistics
    # ------------------------------------------------------------------

    def title_stats(self) -> dict[str, Any]:
        """Analyse article titles.

        Returns:
            Dict with char/word length stats, distribution, structural
            markers, and top first words.
        """
        rows = self._conn.execute(
            "SELECT title FROM articles WHERE is_parsed = 1 AND title != ''"
        ).fetchall()

        titles = [r["title"] for r in rows]
        if not titles:
            return {"mean_chars": 0, "median_chars": 0, "mean_words": 0}

        char_lens = [len(t) for t in titles]
        word_lens = [len(t.split()) for t in titles]
        char_lens.sort()

        mean_chars = sum(char_lens) / len(char_lens)
        median_chars = statistics.median(char_lens)
        mean_words = sum(word_lens) / len(word_lens)

        dist_chars = self._bucket_distribution(char_lens, [40, 60, 80, 100])

        # Structural markers
        starts_with_number = sum(1 for t in titles if re.match(r"^\d+\s", t))
        starts_with_quote = sum(1 for t in titles if re.match(r"^[«\"'']", t))
        starts_with_verb = sum(1 for t in titles if re.match(r"^[Кк]ак\s", t))
        contains_question = sum(1 for t in titles if t.rstrip().endswith("?"))
        contains_colon = sum(1 for t in titles if ": " in t or " :" in t)
        contains_digits = sum(1 for t in titles if re.search(r"\d", t))

        # Top first words
        first_words: Counter = Counter()
        for t in titles:
            words = t.split()
            if words:
                first_words[words[0].strip("«»\"'")] += 1
        top_first = [[w, c] for w, c in first_words.most_common(15)]

        return {
            "mean_chars": round(mean_chars, 1),
            "median_chars": median_chars,
            "mean_words": round(mean_words, 1),
            "distribution_chars": dist_chars,
            "starts_with_number": starts_with_number,
            "starts_with_quote": starts_with_quote,
            "starts_with_verb": starts_with_verb,
            "contains_question": contains_question,
            "contains_colon": contains_colon,
            "contains_digits": contains_digits,
            "top_first_words": top_first,
        }

    # ------------------------------------------------------------------
    # Block 3: Word frequency
    # ------------------------------------------------------------------

    def word_frequency(
        self,
        top_n: int = 200,
        min_length: int = 3,
    ) -> dict[str, Any]:
        """Analyse word frequency in article texts and titles.

        Args:
            top_n: How many top words to return.
            min_length: Minimum word length to include.

        Returns:
            Dict with top words in texts, top words in titles,
            unique word count, and total words analysed.
        """
        rows = self._conn.execute(
            "SELECT text, title FROM articles WHERE is_parsed = 1"
        ).fetchall()

        text_counter: Counter = Counter()
        title_counter: Counter = Counter()
        total_words = 0

        for r in rows:
            text = r["text"] or ""
            title = r["title"] or ""

            # Process text
            tokens = self._tokenize(text, min_length)
            text_counter.update(tokens)
            total_words += len(tokens)

            # Process title
            title_tokens = self._tokenize(title, min_length)
            title_counter.update(title_tokens)

        # Build ranked lists
        top_texts = [
            {"word": w, "count": c, "rank": i + 1}
            for i, (w, c) in enumerate(text_counter.most_common(top_n))
        ]
        top_titles = [
            {"word": w, "count": c, "rank": i + 1}
            for i, (w, c) in enumerate(title_counter.most_common(top_n))
        ]

        return {
            "top_words_in_texts": top_texts,
            "top_words_in_titles": top_titles,
            "unique_words_count": len(text_counter),
            "total_words_analyzed": total_words,
        }

    def _tokenize(self, text: str, min_length: int = 3) -> list[str]:
        """Tokenize text: lowercase, strip punctuation, remove numbers and stop words."""
        text = text.lower()
        tokens = text.split()
        result: list[str] = []
        for token in tokens:
            token = PUNCT_RE.sub("", token).strip()
            if not token:
                continue
            if token.isdigit():
                continue
            if len(token) < min_length:
                continue
            if token in STOP_WORDS:
                continue
            result.append(token)
        return result

    # ------------------------------------------------------------------
    # Block 4: N-grams
    # ------------------------------------------------------------------

    def ngrams_analysis(self, top_n: int = 50) -> dict[str, Any]:
        """Analyse bigrams and trigrams in article titles.

        Args:
            top_n: How many top n-grams to return.

        Returns:
            Dict with top_bigrams and top_trigrams.
        """
        rows = self._conn.execute(
            "SELECT title FROM articles WHERE is_parsed = 1 AND title != ''"
        ).fetchall()

        bigram_counter: Counter = Counter()
        trigram_counter: Counter = Counter()

        for r in rows:
            title = r["title"] or ""
            tokens = self._tokenize(title, min_length=2)

            # Bigrams
            for i in range(len(tokens) - 1):
                bigram = f"{tokens[i]} {tokens[i + 1]}"
                bigram_counter[bigram] += 1

            # Trigrams
            for i in range(len(tokens) - 2):
                trigram = f"{tokens[i]} {tokens[i + 1]} {tokens[i + 2]}"
                trigram_counter[trigram] += 1

        top_bigrams = [
            {"ngram": bg, "count": c}
            for bg, c in bigram_counter.most_common(top_n)
        ]
        top_trigrams = [
            {"ngram": tg, "count": c}
            for tg, c in trigram_counter.most_common(top_n)
        ]

        return {
            "top_bigrams": top_bigrams,
            "top_trigrams": top_trigrams,
        }

    # ------------------------------------------------------------------
    # Block 5: Title patterns
    # ------------------------------------------------------------------

    def title_patterns(self) -> dict[str, Any]:
        """Classify titles by structural patterns.

        Returns:
            Dict with pattern counts, percentages, examples, and
            per-channel breakdown.
        """
        rows = self._conn.execute(
            "SELECT articles.title AS title, slug FROM articles "
            "JOIN channels ON channels.id = articles.channel_id "
            "WHERE is_parsed = 1 AND articles.title != ''"
        ).fetchall()

        pattern_counts: dict[str, int] = {
            "number_list": 0,
            "how_to": 0,
            "quote": 0,
            "question": 0,
            "colon_split": 0,
            "personal_story": 0,
            "age_mention": 0,
            "money_amount": 0,
            "other": 0,
        }
        pattern_examples: dict[str, list[str]] = {k: [] for k in pattern_counts}
        by_channel: dict[str, Counter] = {}
        total = len(rows)

        for r in rows:
            title = r["title"] or ""
            slug = r["slug"]
            matched = False

            # Check each pattern in priority order
            for name, _label, regex in TITLE_PATTERNS:
                if regex.search(title):
                    pattern_counts[name] += 1
                    if len(pattern_examples[name]) < 5:
                        pattern_examples[name].append(title)
                    matched = True
                    break

            # personal_story — check keywords
            if not matched:
                title_lower = title.lower()
                if any(pw in title_lower for pw in PERSONAL_WORDS):
                    pattern_counts["personal_story"] += 1
                    if len(pattern_examples["personal_story"]) < 5:
                        pattern_examples["personal_story"].append(title)
                    matched = True

            if not matched:
                pattern_counts["other"] += 1
                if len(pattern_examples["other"]) < 5:
                    pattern_examples["other"].append(title)

            # Per-channel tracking
            by_channel.setdefault(slug, Counter())
            category = next(
                (name for name, _label, regex in TITLE_PATTERNS if regex.search(title)),
                None,
            )
            if category:
                by_channel[slug][category] += 1
            else:
                title_lower = title.lower()
                if any(pw in title_lower for pw in PERSONAL_WORDS):
                    by_channel[slug]["personal_story"] += 1
                else:
                    by_channel[slug]["other"] += 1

        # Build result
        patterns_result: dict[str, Any] = {}
        for name in pattern_counts:
            patterns_result[name] = {
                "count": pattern_counts[name],
                "percent": round(
                    pattern_counts[name] / total * 100, 1
                ) if total > 0 else 0.0,
                "examples": pattern_examples[name],
            }

        # Most common overall
        most_common = max(pattern_counts, key=pattern_counts.get)

        # Per-channel most common
        by_channel_result: dict[str, str] = {}
        for slug, counter in by_channel.items():
            if counter:
                by_channel_result[slug] = counter.most_common(1)[0][0]

        return {
            "patterns": patterns_result,
            "most_common": most_common,
            "by_channel": by_channel_result,
        }

    # ------------------------------------------------------------------
    # Block 6: Structure statistics
    # ------------------------------------------------------------------

    def structure_stats(self) -> dict[str, Any]:
        """Analyse article structure: paragraphs, headers, images.

        Returns:
            Dict with mean/median/distribution for paragraphs, headers,
            and images, plus per-channel breakdown.
        """
        rows = self._conn.execute(
            "SELECT paragraphs_count, headers_count, images_count, slug "
            "FROM articles "
            "JOIN channels ON channels.id = articles.channel_id "
            "WHERE is_parsed = 1"
        ).fetchall()

        paragraphs: list[int] = []
        headers: list[int] = []
        images: list[int] = []
        by_channel: dict[str, dict[str, list[int]]] = {}

        for r in rows:
            p = r["paragraphs_count"] or 0
            h = r["headers_count"] or 0
            im = r["images_count"] or 0
            slug = r["slug"]

            paragraphs.append(p)
            headers.append(h)
            images.append(im)

            by_channel.setdefault(slug, {"paragraphs": [], "headers": [], "images": []})
            by_channel[slug]["paragraphs"].append(p)
            by_channel[slug]["headers"].append(h)
            by_channel[slug]["images"].append(im)

        n = len(paragraphs)

        def _stats(arr: list[int]) -> dict[str, Any]:
            if not arr:
                return {"mean": 0.0, "median": 0, "total": 0}
            return {
                "mean": round(sum(arr) / len(arr), 1),
                "median": statistics.median(sorted(arr)),
                "total": len(arr),
            }

        # Build per-channel stats
        by_channel_stats: dict[str, dict[str, Any]] = {}
        for slug, data in by_channel.items():
            by_channel_stats[slug] = {
                "paragraphs": _stats(data["paragraphs"]),
                "headers": _stats(data["headers"]),
                "images": _stats(data["images"]),
            }

        # Articles with headers / images
        articles_with_headers = sum(1 for h in headers if h > 0)
        articles_with_images = sum(1 for im in images if im > 0)

        return {
            "paragraphs": {
                "mean": _stats(paragraphs)["mean"],
                "median": _stats(paragraphs)["median"],
                "distribution": self._bucket_distribution(
                    paragraphs, [5, 10, 20]
                ),
            },
            "headers": {
                "mean": _stats(headers)["mean"],
                "articles_with_headers": articles_with_headers,
                "articles_without_headers": n - articles_with_headers,
                "percent_with_headers": round(
                    articles_with_headers / n * 100, 1
                ) if n > 0 else 0.0,
            },
            "images": {
                "mean": _stats(images)["mean"],
                "articles_with_images": articles_with_images,
                "percent_with_images": round(
                    articles_with_images / n * 100, 1
                ) if n > 0 else 0.0,
            },
            "by_channel": by_channel_stats,
        }

    # ------------------------------------------------------------------
    # Block 7: Publication time statistics
    # ------------------------------------------------------------------

    def publication_time_stats(self) -> dict[str, Any]:
        """Analyse publication times.

        Returns:
            Dict with counts by day of week and by hour, plus
            most active day and hour.
        """
        rows = self._conn.execute(
            "SELECT published_at FROM articles "
            "WHERE is_parsed = 1 AND published_at IS NOT NULL"
        ).fetchall()

        day_names = [
            "Понедельник", "Вторник", "Среда",
            "Четверг", "Пятница", "Суббота", "Воскресенье",
        ]
        by_day: Counter = Counter()
        by_hour: Counter = Counter()

        for r in rows:
            try:
                dt_str = r["published_at"]
                if not dt_str:
                    continue
                # Handle ISO format with timezone
                dt_str = dt_str[:19]  # strip timezone
                dt = datetime.fromisoformat(dt_str)
                by_day[day_names[dt.weekday()]] += 1
                by_hour[str(dt.hour)] += 1
            except (ValueError, IndexError, TypeError):
                continue

        # Fill missing hours
        for h in range(24):
            hour_key = str(h)
            if hour_key not in by_hour:
                by_hour[hour_key] = 0

        by_hour_sorted = {
            str(h): by_hour.get(str(h), 0) for h in range(24)
        }

        most_active_day = by_day.most_common(1)[0][0] if by_day else "?"
        most_active_hour = int(by_hour.most_common(1)[0][0]) if by_hour else 0

        return {
            "by_day_of_week": dict(by_day),
            "by_hour": by_hour_sorted,
            "most_active_day": most_active_day,
            "most_active_hour": most_active_hour,
        }

    # ------------------------------------------------------------------
    # Block 8: Full analysis
    # ------------------------------------------------------------------

    def run_full_analysis(self) -> dict[str, Any]:
        """Run all analysis methods and return a combined report.

        Returns:
            Dict with all analysis blocks.
        """
        logger.info("Starting full article corpus analysis...")
        start = time.time()

        # Corpus overview
        corpus = self._conn.execute(
            "SELECT COUNT(*) AS articles, "
            "(SELECT COUNT(*) FROM channels WHERE is_active = 1) AS channels "
            "FROM articles WHERE is_parsed = 1"
        ).fetchone()

        result: dict[str, Any] = {
            "generated_at": datetime.now().isoformat()[:19],
            "corpus": {
                "total_articles": corpus["articles"],
                "total_channels": corpus["channels"],
            },
        }

        # Block 1: Text length
        t0 = time.time()
        result["text_length"] = self.text_length_stats()
        logger.info("  text_length_stats: %.2fs", time.time() - t0)

        # Block 2: Titles
        t0 = time.time()
        result["titles"] = self.title_stats()
        logger.info("  title_stats: %.2fs", time.time() - t0)

        # Block 3: Word frequency
        t0 = time.time()
        result["word_frequency"] = self.word_frequency()
        logger.info("  word_frequency: %.2fs", time.time() - t0)

        # Block 4: N-grams
        t0 = time.time()
        result["ngrams"] = self.ngrams_analysis()
        logger.info("  ngrams_analysis: %.2fs", time.time() - t0)

        # Block 5: Title patterns
        t0 = time.time()
        result["title_patterns"] = self.title_patterns()
        logger.info("  title_patterns: %.2fs", time.time() - t0)

        # Block 6: Structure
        t0 = time.time()
        result["structure"] = self.structure_stats()
        logger.info("  structure_stats: %.2fs", time.time() - t0)

        # Block 7: Publication time
        t0 = time.time()
        result["publication_time"] = self.publication_time_stats()
        logger.info("  publication_time_stats: %.2fs", time.time() - t0)

        elapsed = time.time() - start
        logger.info(
            "Full analysis complete in %.2fs: %d articles, %d channels",
            elapsed,
            result["corpus"]["total_articles"],
            result["corpus"]["total_channels"],
        )

        return result

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _bucket_distribution(
        values: list[int],
        thresholds: list[int],
    ) -> dict[str, int]:
        """Partition *values* into buckets defined by *thresholds*.

        Example::

            _bucket_distribution([100, 250, 600], [200, 400, 600])
            → {"0-200": 1, "200-400": 1, "400-600": 0, "600+": 1}
        """
        buckets: dict[str, int] = {}
        prev = 0
        for t in thresholds:
            label = f"{prev}-{t}"
            buckets[label] = sum(1 for v in values if prev <= v < t)
            prev = t
        buckets[f"{prev}+"] = sum(1 for v in values if v >= prev)
        return buckets

    def close(self) -> None:
        """Close the database connection."""
        try:
            self._conn.close()
            logger.info("ArticleStatistics closed: %s", self._db_path)
        except Exception:
            logger.exception("Error closing ArticleStatistics")