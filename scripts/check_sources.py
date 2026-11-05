#!/usr/bin/env python3
"""Read-only live source check. Never sends Discord messages or changes state."""
import argparse
import logging
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import WATCHERS


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources', nargs='*', choices=sorted(WATCHERS))
    args = parser.parse_args()
    failures = 0
    for name in args.sources or WATCHERS:
        try:
            postings = WATCHERS[name]()
            print(f'{name}: {len(postings)} verified listings')
            for p in postings:
                print(f'  {p.job_id or "-"} | {p.title} | {p.location} | {p.url}')
        except Exception as error:
            failures += 1
            print(f'{name}: FAILED ({type(error).__name__}): {error}', file=sys.stderr)
    return bool(failures)


if __name__ == '__main__':
    sys.exit(main())
