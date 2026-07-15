import datetime
import json
import os
import tempfile
import unittest
from unittest import mock

import build


class HistoryTests(unittest.TestCase):
    def test_artifact_metadata_uses_observation_dates(self):
        rows = [
            {"source": "market", "date": datetime.date(2026, 7, 14), "ok": True, "stale": False},
            {"source": "manual", "date": datetime.date(2026, 6, 30), "ok": True, "stale": True},
            {"source": "derived", "date": None, "ok": True, "stale": False},
        ]
        generated = datetime.datetime(2026, 7, 15, tzinfo=datetime.timezone.utc)
        with mock.patch.dict(os.environ, {"GITHUB_SHA": "abcdef1234567890"}):
            meta = build._artifact_metadata(rows, {"margin": 7.5}, generated)

        self.assertEqual(meta["market_as_of"], "2026-07-14")
        self.assertEqual(meta["manual_as_of"], "2026-06-30")
        self.assertEqual(meta["model_version"], "india-risk-v2")
        self.assertEqual(meta["source_sha"], "abcdef123456")
        self.assertEqual(meta["source_counts"]["manual"], {"total": 1, "live": 1, "stale": 1})

    def test_snapshots_are_immutable_and_old_history_compacts_monthly(self):
        with tempfile.TemporaryDirectory() as directory:
            def archive(iso):
                return build._archive_snapshot({"generated": iso, "value": iso}, directory)

            first = archive("2020-01-01T00:00:00+00:00")
            january_latest = archive("2020-01-31T00:00:00+00:00")
            february = archive("2020-02-01T00:00:00+00:00")
            recent = archive("2026-07-15T00:00:00+00:00")

            with self.assertRaises(FileExistsError):
                archive("2026-07-15T00:00:00+00:00")

            removed = build._compact_history(
                directory, keep_daily_days=730, today=datetime.date(2026, 7, 15))

            self.assertEqual(removed, 1)
            self.assertFalse(os.path.exists(first))
            expected = {
                january_latest: "2020-01-31T00:00:00+00:00",
                february: "2020-02-01T00:00:00+00:00",
                recent: "2026-07-15T00:00:00+00:00",
            }
            for path, generated in expected.items():
                self.assertTrue(os.path.exists(path))
                with open(path, encoding="utf-8") as f:
                    self.assertEqual(json.load(f)["generated"], generated)


if __name__ == "__main__":
    unittest.main()
