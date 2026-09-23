"""SQLite persistence and exports."""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

FIELDS = ("platform", "post_id", "url", "author", "source", "cities", "category",
          "text", "published_at", "event_date")


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("""CREATE TABLE IF NOT EXISTS posts (
        platform TEXT NOT NULL,
        post_id TEXT NOT NULL,
        url TEXT NOT NULL UNIQUE,
        author TEXT NOT NULL,
        source TEXT NOT NULL,
        cities TEXT NOT NULL,
        category TEXT NOT NULL,
        text TEXT NOT NULL,
        published_at TEXT,
        event_date TEXT,
        collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (platform, post_id)
    )""")
    db.commit()
    return db


def save(db: sqlite3.Connection, item: dict[str, Any]) -> bool:
    row = [json.dumps(item[k], ensure_ascii=False) if k == "cities" else item[k] for k in FIELDS]
    before = db.total_changes
    db.execute("""INSERT OR IGNORE INTO posts
        (platform, post_id, url, author, source, cities, category, text, published_at, event_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", row)
    db.commit()
    return db.total_changes > before


def export(db: sqlite3.Connection, path: Path, fmt: str, city: str | None = None,
           category: str | None = None) -> int:
    if fmt not in {"json", "csv"}:
        raise ValueError("format must be json or csv")
    query = "SELECT " + ", ".join(FIELDS) + " FROM posts WHERE 1=1"
    params: list[str] = []
    if city:
        query += " AND EXISTS (SELECT 1 FROM json_each(posts.cities) WHERE value = ?)"
        params.append(city)
    if category:
        query += " AND category = ?"
        params.append(category)
    query += " ORDER BY published_at DESC, collected_at DESC"
    rows = [dict(zip(FIELDS, row)) for row in db.execute(query, params)]
    for row in rows:
        row["cities"] = json.loads(row["cities"])
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            for row in rows:
                row["cities"] = ",".join(row["cities"])
                writer.writerow(row)
    return len(rows)
