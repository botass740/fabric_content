"""
CLI for running the full statistical analysis on the article corpus.

Usage::

    python tools/run_statistics.py
    python tools/run_statistics.py --db data/research.db --output data/report.json
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure the project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.statistics import ArticleStatistics


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Statistical analysis of the Dzen article corpus."
    )
    parser.add_argument(
        "--db",
        default="data/research.db",
        help="Research database path (default: %(default)s)",
    )
    parser.add_argument(
        "--output",
        default="data/statistics_report.json",
        help="Output JSON path (default: %(default)s)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    if not Path(args.db).exists():
        print(f"ERROR: Database not found: {args.db}")
        sys.exit(1)

    print("=" * 60)
    print("  Dzen Article Corpus — Statistical Analysis")
    print("=" * 60)
    print(f"  Database: {args.db}")
    print(f"  Output:   {args.output}")
    print()

    stats = ArticleStatistics(args.db)

    try:
        result = stats.run_full_analysis()

        # Save full report
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\nFull report saved: {output_path}")

        # ---- Console summary ----
        print("\n" + "=" * 60)
        print("  SUMMARY")
        print("=" * 60)

        corpus = result["corpus"]
        print(f"\n  Corpus: {corpus['total_articles']} articles, "
              f"{corpus['total_channels']} channels")

        # Text length
        tl = result["text_length"]
        if tl.get("total_articles", 0) > 0:
            print(f"\n  Text length (words):")
            print(f"    Mean:   {tl['mean_words']:.0f}")
            print(f"    Median: {tl['median_words']:.0f}")
            print(f"    Min:    {tl['min_words']}")
            print(f"    Max:    {tl['max_words']}")
            print(f"    Std:    {tl['std_words']:.0f}")
            print(f"    Distr:  {dict(sorted(tl['distribution'].items()))}")

        # Titles
        titles = result["titles"]
        if titles.get("mean_chars", 0) > 0:
            print(f"\n  Titles:")
            print(f"    Mean chars:      {titles['mean_chars']:.0f}")
            print(f"    Mean words:      {titles['mean_words']:.0f}")
            print(f"    With question:   {titles['contains_question']}")
            print(f"    With colon:      {titles['contains_colon']}")
            print(f"    With digits:     {titles['contains_digits']}")
            print(f"    Start with number: {titles['starts_with_number']}")
            print(f"    Start with 'How':  {titles['starts_with_verb']}")
            print(f"    Top first words:   ", end="")
            fw = titles.get("top_first_words", [])
            for w, c in fw[:5]:
                w_safe = w.encode("ascii", errors="replace").decode("ascii")
                print(f"'{w_safe}'({c}) ", end="")
            print()

        # Word frequency
        wf = result["word_frequency"]
        if wf.get("top_words_in_texts"):
            print(f"\n  Top 10 words in texts:")
            for item in wf["top_words_in_texts"][:10]:
                w_safe = item['word'].encode("ascii", errors="replace").decode("ascii")
                print(f"    {item['rank']:2}. {w_safe:<20} {item['count']:>4}")
            print(f"    Unique words: {wf['unique_words_count']:,}")

        if wf.get("top_words_in_titles"):
            print(f"\n  Top 10 words in titles:")
            for item in wf["top_words_in_titles"][:10]:
                w_safe = item['word'].encode("ascii", errors="replace").decode("ascii")
                print(f"    {item['rank']:2}. {w_safe:<20} {item['count']:>4}")

        # N-grams
        ng = result["ngrams"]
        if ng.get("top_bigrams"):
            print(f"\n  Top 5 bigrams in titles:")
            for item in ng["top_bigrams"][:5]:
                ng_safe = item['ngram'].encode("ascii", errors="replace").decode("ascii")
                print(f"    '{ng_safe}': {item['count']}")

        # Title patterns
        tp = result["title_patterns"]
        if tp.get("patterns"):
            print(f"\n  Title patterns:")
            sorted_patterns = sorted(
                tp["patterns"].items(),
                key=lambda x: x[1]["count"],
                reverse=True,
            )
            for name, data in sorted_patterns:
                bar = "#" * int(data["percent"] / 2)
                print(f"    {name:<20} {data['count']:>3} ({data['percent']:>5.1f}%) {bar}")

        # Structure
        struct = result["structure"]
        if struct.get("paragraphs"):
            print(f"\n  Structure:")
            p = struct["paragraphs"]
            h = struct["headers"]
            im = struct["images"]
            print(f"    Paragraphs:     mean {p['mean']:.0f}, median {p['median']:.0f}")
            print(f"    Headers:        mean {h['mean']:.1f}, "
                  f"{h['percent_with_headers']:.0f}% articles have headers")
            print(f"    Images:         mean {im['mean']:.1f}, "
                  f"{im['percent_with_images']:.0f}% articles have images")

        # Publication time
        pt = result["publication_time"]
        if pt.get("by_day_of_week"):
            print(f"\n  Publication time:")
            print(f"    Most active day: {pt['most_active_day']} "
                  f"({pt['by_day_of_week'].get(pt['most_active_day'], 0)} articles)")
            print(f"    Most active hour: {pt['most_active_hour']}:00")
            print(f"    By day: {dict(sorted(pt['by_day_of_week'].items(), key=lambda x: x[1], reverse=True))}")

        print("\n" + "=" * 60)
        print("  DONE")
        print("=" * 60)

    except Exception:
        logging.exception("Analysis failed")
        sys.exit(1)
    finally:
        stats.close()


if __name__ == "__main__":
    main()