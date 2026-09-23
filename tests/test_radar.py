import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from food_radar.classifier import normalize
from food_radar.cli import main
from food_radar.sources import build_jobs, run_job
from food_radar.storage import connect, export, save


def recent(days=0):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


class ClassificationTests(unittest.TestCase):
    def test_instagram_event_and_city_from_caption(self):
        event_date = (datetime.now(timezone.utc) + timedelta(days=5)).date()
        row = {"id": "123", "shortCode": "abc", "caption": f"Алматы: гастроужин в ресторане {event_date:%d.%m.%Y}",
               "url": "https://www.instagram.com/p/abc/?utm_source=test", "timestamp": recent()}
        result = normalize(row, "instagram", "#алматыеда")
        self.assertEqual(result["cities"], ["almaty"])
        self.assertEqual(result["category"], "event")
        self.assertEqual(result["event_date"], event_date.isoformat())
        self.assertEqual(result["url"], "https://www.instagram.com/p/abc/")

    def test_threads_promotion_and_source_city(self):
        row = {"post_id": "77", "text": "Скидка 20% на меню кафе до воскресенья",
               "url": "https://www.threads.com/@cafe/post/abc", "username": "cafe", "posted_at": recent()}
        result = normalize(row, "threads", "cafe", {"cafe": "astana"})
        self.assertEqual(result["cities"], ["astana"])
        self.assertEqual(result["category"], "promotion")

    def test_industry_national_and_nonfood_rejected(self):
        industry = {"post_id": "9", "text": "FoodTech Казахстан: исследование рынка доставки еды",
                    "url": "https://www.threads.com/@news/post/9", "posted_at": recent()}
        self.assertEqual(normalize(industry, "threads", "foodtech")["cities"], ["kazakhstan"])
        nonfood = {**industry, "text": "Астана: скидка на обувь"}
        self.assertIsNone(normalize(nonfood, "threads", "sale"))

    def test_old_post_and_invalid_url_rejected(self):
        row = {"post_id": "9", "text": "Алматы ресторан: открытие",
               "url": "https://www.threads.com/@news/post/9", "posted_at": recent(30)}
        self.assertIsNone(normalize(row, "threads", "search"))
        row["posted_at"] = recent()
        row["url"] = "https://example.com/post/9"
        self.assertIsNone(normalize(row, "threads", "search"))

    def test_past_event_is_rejected(self):
        event_date = (datetime.now(timezone.utc) - timedelta(days=2)).date()
        row = {"post_id": "10", "text": f"Астана ресторан: гастроужин {event_date:%d.%m.%Y}",
               "url": "https://www.threads.com/@news/post/10", "posted_at": recent()}
        self.assertIsNone(normalize(row, "threads", "search"))


class StorageAndCLITests(unittest.TestCase):
    def test_dedup_and_filtered_export(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "radar.db"
            out = Path(temp) / "result.json"
            event_date = (datetime.now(timezone.utc) + timedelta(days=5)).date()
            row = {"post_id": "77", "text": f"Астана ресторан: гастроужин {event_date:%d.%m.%Y}",
                   "url": "https://www.threads.com/@cafe/post/abc", "posted_at": recent()}
            item = normalize(row, "threads", "search")
            with connect(db_path) as db:
                self.assertTrue(save(db, item))
                self.assertFalse(save(db, item))
                self.assertEqual(export(db, out, "json", city="astana", category="event"), 1)
            self.assertEqual(len(json.loads(out.read_text())), 1)

    def test_ingest_and_export_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.json"
            config.write_text('{"source_cities": {"cafe": "astana"}}')
            source = root / "input.json"
            source.write_text(json.dumps([{"post_id": "1", "username": "cafe",
                "text": "Акция на меню кафе", "url": "https://www.threads.com/@cafe/post/1",
                "posted_at": recent()}]))
            args = ["ingest", str(source), "--platform", "threads", "--source", "cafe",
                    "--config", str(config), "--db", str(root / "radar.db")]
            self.assertEqual(main(args), 0)
            self.assertEqual(main(args), 0)
            out = root / "out.csv"
            self.assertEqual(main(["export", "--db", str(root / "radar.db"),
                                   "--city", "astana", "--out", str(out)]), 0)
            self.assertEqual(len(out.read_text().splitlines()), 2)

    def test_job_plan_and_spending_cap(self):
        jobs = build_jobs({"instagram_profiles": ["@cafe"], "threads_queries": ["Алматы ресторан"]})
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0].payload["resultsLimit"], 10)
        with patch("food_radar.sources.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b"[]"
            self.assertEqual(run_job(jobs[0], "secret", 0.10), [])
            req = urlopen.call_args.args[0]
            self.assertIn("maxTotalChargeUsd=0.1", req.full_url)
            self.assertEqual(req.get_header("Authorization"), "Bearer secret")
            self.assertNotIn("secret", req.full_url)


if __name__ == "__main__":
    unittest.main()
