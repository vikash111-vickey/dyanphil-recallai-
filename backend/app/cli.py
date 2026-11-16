"""Command-line interface for Dyanphil indexer and search assistant."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from app.db import get_connection, get_stats, init_db, search_fts
from app.ingestion.scanner import index_folders


def handle_index(args: argparse.Namespace) -> int:
    """Handle the 'index' CLI command."""
    folders = [Path(f) for f in args.folders]
    invalid_folders = [f for f in folders if not f.exists() or not f.is_dir()]
    if invalid_folders:
        for f in invalid_folders:
            print(f"Warning: Directory does not exist or is not a folder: {f}", file=sys.stderr)

    valid_folders = [f for f in folders if f.exists() and f.is_dir()]
    if not valid_folders:
        print("Error: No valid folders provided to index.", file=sys.stderr)
        return 1

    stats = index_folders(valid_folders)
    print(f"Scanned:   {stats.scanned}")
    print(f"Indexed:   {stats.indexed}")
    print(f"Skipped:   {stats.skipped}")
    print(f"Unchanged: {stats.unchanged}")
    print(f"Failed:    {stats.failed}")
    print(f"Needs OCR: {stats.needs_ocr}")
    return 0


def handle_search(args: argparse.Namespace) -> int:
    """Handle the 'search' CLI command."""
    query = args.words.strip()
    if not query:
        print("Error: Search query cannot be empty.", file=sys.stderr)
        return 1

    conn = get_connection()
    try:
        init_db(conn)
        results = search_fts(conn, query, limit=args.limit)

        if not results:
            print(f"No results found for '{query}'.")
            return 0

        print(f"Found {len(results)} match(es) for '{query}':\n")
        for item in results:
            mtime_dt = datetime.fromtimestamp(item["modified_at"]).strftime("%Y-%m-%d %H:%M:%S")
            snippet = item["snippet"].replace("\n", " ").strip()
            print(f"Rank {item['rank']}: {item['filename']}")
            print(f"  Path:     {item['path']}")
            print(f"  Modified: {mtime_dt}")
            print(f"  Snippet:  {snippet}")
            print()
        return 0
    finally:
        conn.close()


def handle_stats(args: argparse.Namespace) -> int:
    """Handle the 'stats' CLI command."""
    conn = get_connection()
    try:
        init_db(conn)
        stats = get_stats(conn)

        print(f"Total files: {stats['total_files']}")

        print("\nFiles by status:")
        if stats["by_status"]:
            for status, count in stats["by_status"].items():
                print(f"  {status}: {count}")
        else:
            print("  (none)")

        print("\nFiles by extension:")
        if stats["by_extension"]:
            for ext, count in stats["by_extension"].items():
                print(f"  {ext}: {count}")
        else:
            print("  (none)")

        return 0
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point using argparse."""
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Dyanphil - Local personal search assistant CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: index
    index_parser = subparsers.add_parser("index", help="Index one or more directories")
    index_parser.add_argument(
        "folders",
        nargs="+",
        help="One or more directory paths to index",
    )
    index_parser.set_defaults(handler=handle_index)

    # Subcommand: search
    search_parser = subparsers.add_parser("search", help="Search the index using FTS5 keywords")
    search_parser.add_argument(
        "words",
        type=str,
        help="Keywords or query terms to search",
    )
    search_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of search results (default: 10)",
    )
    search_parser.set_defaults(handler=handle_search)

    # Subcommand: stats
    stats_parser = subparsers.add_parser("stats", help="Display index statistics")
    stats_parser.set_defaults(handler=handle_stats)

    parsed_args = parser.parse_args(argv)
    return parsed_args.handler(parsed_args)


if __name__ == "__main__":
    sys.exit(main())
