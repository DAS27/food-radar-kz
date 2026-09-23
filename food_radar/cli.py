"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .classifier import normalize
from .sources import build_jobs, run_job
from .storage import connect, export, save


def _read_config(path: Path) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Config must be a JSON object")
    return config


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Restaurant, HoReCa and FoodTech radar for Kazakhstan")
    sub = parser.add_subparsers(dest="command", required=True)
    collect = sub.add_parser("collect", help="Run configured Apify searches")
    collect.add_argument("--config", type=Path, default=Path("config.json"))
    collect.add_argument("--db", type=Path, default=Path("radar.db"))
    collect.add_argument("--max-charge-usd", type=float, default=0.10,
                         help="Apify spending cap per actor run (default: $0.10)")
    collect.add_argument("--max-runs", type=int, default=8,
                         help="Maximum actor runs in this invocation (default: 8)")
    collect.add_argument("--dry-run", action="store_true", help="Show planned jobs and maximum spend")
    ingest = sub.add_parser("ingest", help="Import a JSON export from an Apify Actor")
    ingest.add_argument("file", type=Path)
    ingest.add_argument("--platform", choices=["instagram", "threads"], required=True)
    ingest.add_argument("--source", required=True, help="Profile, hashtag or search query")
    ingest.add_argument("--config", type=Path, default=Path("config.json"))
    ingest.add_argument("--db", type=Path, default=Path("radar.db"))
    exp = sub.add_parser("export", help="Export saved posts")
    exp.add_argument("--db", type=Path, default=Path("radar.db"))
    exp.add_argument("--out", type=Path, required=True)
    exp.add_argument("--city", choices=["almaty", "astana", "kazakhstan"])
    exp.add_argument("--category", choices=["event", "promotion", "industry", "food_news"])
    return parser.parse_args(argv)


def _ingest_rows(db, rows: list, platform: str, source: str, source_cities: dict,
                 max_post_age_days: int) -> tuple[int, int]:
    accepted = new = 0
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        item = normalize(raw, platform, source, source_cities, max_post_age_days)
        if item:
            accepted += 1
            new += save(db, item)
    return accepted, new


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.command == "export":
            with connect(args.db) as db:
                count = export(db, args.out, args.out.suffix.lstrip(".").lower(), args.city, args.category)
            print(f"Exported {count} posts to {args.out}")
            return 0
        config = _read_config(args.config)
        source_cities = config.get("source_cities", {})
        if not isinstance(source_cities, dict):
            raise ValueError("source_cities must be a JSON object")
        max_post_age_days = int(config.get("max_post_age_days", 14))
        if not 1 <= max_post_age_days <= 365:
            raise ValueError("max_post_age_days must be between 1 and 365")
        if args.command == "ingest":
            rows = json.loads(args.file.read_text(encoding="utf-8"))
            if not isinstance(rows, list):
                raise ValueError("Input file must contain a JSON array")
            with connect(args.db) as db:
                accepted, new = _ingest_rows(db, rows, args.platform, args.source,
                                             source_cities, max_post_age_days)
            print(f"Relevant: {accepted}; new: {new}")
            return 0
        jobs = build_jobs(config)
        if args.max_runs < 1 or not 0 < args.max_charge_usd <= 5:
            raise ValueError("max-runs must be positive and max-charge-usd must be in (0, 5]")
        jobs = jobs[:args.max_runs]
        if not jobs:
            raise ValueError("No sources configured")
        if args.dry_run:
            for job in jobs:
                print(f"{job.platform}: {job.source} ({job.actor})")
            print(f"Maximum charge across these runs: ${len(jobs) * args.max_charge_usd:.2f}")
            return 0
        token = os.environ.get("APIFY_TOKEN", "").strip()
        if not token:
            raise ValueError("Set APIFY_TOKEN to collect live data; use --dry-run to preview")
        with connect(args.db) as db:
            total_new = 0
            failures = 0
            for job in jobs:
                try:
                    rows = run_job(job, token, args.max_charge_usd)
                    accepted, new = _ingest_rows(db, rows, job.platform, job.source,
                                                 source_cities, max_post_age_days)
                    total_new += new
                    print(f"{job.platform} {job.source}: received {len(rows)}, relevant {accepted}, new {new}")
                except RuntimeError as exc:
                    failures += 1
                    print(f"{job.platform} {job.source}: {exc}", file=sys.stderr)
            print(f"New posts saved: {total_new}; failed runs: {failures}")
            return 1 if failures else 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
