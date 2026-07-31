"""
CLI entry point for the Dzen channel finder.

Search, evaluate, and save financial channels from Dzen.

Usage::

    # Evaluate a single channel
    python tools/run_channel_finder.py --evaluate https://dzen.ru/vzoprodengi

    # Search by one query
    python tools/run_channel_finder.py --query "финансовая грамотность"

    # Full search across all queries + save to DB
    python tools/run_channel_finder.py --find-all --save --min-score 50
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Ensure the project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.channel_finder import ChannelFinder


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Auto-discovery of financial channels on Dzen."
    )
    parser.add_argument(
        "--query",
        help="Search channels by a single query",
    )
    parser.add_argument(
        "--evaluate",
        help="Evaluate a specific channel URL",
    )
    parser.add_argument(
        "--find-all",
        action="store_true",
        help="Full search across all predefined queries",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save found channels to the research database",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=40,
        help="Minimum score for saving (default: %(default)s)",
    )
    parser.add_argument(
        "--max-channels",
        type=int,
        default=30,
        help="Max channels to return from find-all (default: %(default)s)",
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

    finder = ChannelFinder(state_path=args.state, db_path=args.db)

    try:
        # ---- Mode 1: evaluate a single channel ----
        if args.evaluate:
            print(f"\nEvaluating channel: {args.evaluate}")
            result = await finder.evaluate_channel(args.evaluate)
            if result:
                print(f"\n  Channel:    {result['slug']}")
                print(f"  Title:      {result.get('title', '--')}")
                print(f"  Subscribers: {result.get('subscribers_raw', '?')} "
                      f"({result.get('subscribers', 0):,})")
                print(f"  Last article: {result.get('last_article_date', '--')} "
                      f"({result.get('days_inactive', '?')} days ago)")
                print(f"  Visible articles: {result.get('articles_visible', 0)}")
                print(f"  Finance topic: {'YES' if result.get('is_finance') else 'NO'}")
                print(f"  Score:      {result['score']}/100")
                print(f"  Recommend:  {'YES - add to crawl' if result.get('add_to_crawl') else 'NO - skip'}")
            else:
                print("\n  ERROR: channel is unreachable or not found")

        # ---- Mode 2: search by one query ----
        elif args.query:
            print(f"\nSearching: {args.query}")
            channels = await finder.search_channels_by_query(args.query)
            print(f"\nFound {len(channels)} channel(s):")
            for ch in channels:
                print(f"  {ch['url']}")

        # ---- Mode 3: full search and evaluate ----
        elif args.find_all:
            print(f"\nFull search across all queries ...")
            print(f"Max channels: {args.max_channels}")
            print(f"Min score:    {args.min_score}")
            print()

            channels = await finder.find_and_evaluate(
                max_channels=args.max_channels,
            )

            if not channels:
                print("\nNo new channels found.")
                return

            print(f"\n{'=' * 70}")
            print(f"Found and evaluated: {len(channels)} channels")
            print(f"{'=' * 70}")
            print(
                f"{'Slug':<28} {'Score':>6} {'Subs':>10} {'Inactive':>10} {'Finance':>8} {'Add':>5}"
            )
            print("-" * 70)
            for ch in channels:
                print(
                    f"{ch['slug']:<28} "
                    f"{ch['score']:>6} "
                    f"{ch.get('subscribers_raw', '?'):>10} "
                    f"{ch.get('days_inactive', '?'):>5}d "
                    f"{'YES' if ch.get('is_finance') else 'no':>8} "
                    f"{'YES' if ch.get('add_to_crawl') else 'no':>5}"
                )

            if args.save:
                saved = finder.save_found_channels(
                    channels,
                    min_score=args.min_score,
                )
                print(f"\nSaved to DB: {saved} channels (score >= {args.min_score})")

        else:
            parser.print_help()

    finally:
        finder.close()


if __name__ == "__main__":
    asyncio.run(main())