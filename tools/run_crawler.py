"""
CLI entry point for the Dzen research crawler.

Crawl one channel or all channels from a seed file.

Usage::

    # Crawl a single channel
    python tools/run_crawler.py --channel https://dzen.ru/igorfaynman

    # Crawl all channels from seed
    python tools/run_crawler.py --seed tools/dzen_channels_seed.txt --max-articles 50
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Ensure the project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.crawler import ResearchCrawler


def setup_logging(verbose: bool = False) -> None:
    """Configure logging to show INFO-level messages by default."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawler for Dzen articles — collect, parse, and store."
    )
    parser.add_argument(
        "--channel",
        help="Single channel URL, e.g. https://dzen.ru/igorfaynman",
    )
    parser.add_argument(
        "--seed",
        default="tools/dzen_channels_seed.txt",
        help="File with channel URLs, one per line (default: %(default)s)",
    )
    parser.add_argument(
        "--max-articles",
        type=int,
        default=50,
        help="Max articles per channel (default: %(default)s)",
    )
    parser.add_argument(
        "--state",
        default="dzen_state.json",
        help="Playwright storage state path (default: %(default)s)",
    )
    parser.add_argument(
        "--db",
        default="data/research.db",
        help="Research database path (default: %(default)s)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    if not Path(args.state).exists():
        print(f"ERROR: State file not found: {args.state}")
        print("Run 'dzen_auth_explorer.py' first to log in.")
        sys.exit(1)

    crawler = ResearchCrawler(state_path=args.state, db_path=args.db)

    try:
        if args.channel:
            # Crawl a single channel
            print(f"\nCrawling channel: {args.channel}")
            print(f"Max articles: {args.max_articles}")
            print(f"State file:   {args.state}")
            print(f"Database:     {args.db}\n")

            result = await crawler.crawl_channel(
                args.channel,
                max_articles=args.max_articles,
            )

            print(f"\nResults for {args.channel}:")
            print(f"  Articles found:  {result['articles_found']}")
            print(f"  New articles:    {result['articles_new']}")
            print(f"  Skipped (known): {result['articles_skipped']}")
            print(f"  Errors:          {result['errors']}")

        else:
            # Crawl from seed file
            seed_path = Path(args.seed)
            if not seed_path.exists():
                print(f"ERROR: Seed file not found: {args.seed}")
                sys.exit(1)

            print(f"\nCrawling from seed file: {args.seed}")
            print(f"Max articles per channel: {args.max_articles}")
            print(f"State file:              {args.state}")
            print(f"Database:                {args.db}\n")

            result = await crawler.crawl_from_seed(
                args.seed,
                max_articles_per_channel=args.max_articles,
            )

            print(f"\nAggregate results:")
            print(f"  Channels processed: {result['channels_count']}")
            print(f"  Articles found:     {result['articles_found']}")
            print(f"  New articles:       {result['articles_new']}")
            print(f"  Errors:             {result['errors']}")

    finally:
        crawler.close()


if __name__ == "__main__":
    asyncio.run(main())