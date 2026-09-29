import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from update_contribution_chart import date_ranges, fetch_history, parse_calendar, render_svg, summarize


class ContributionHistoryTests(unittest.TestCase):
    def test_ranges_cover_leap_year_without_gaps_or_overlap(self):
        first, last = date(2023, 12, 30), date(2025, 1, 2)
        actual = []
        for start, end in date_ranges(first, last):
            self.assertLessEqual((end - start).days, 89)
            actual.extend(start + timedelta(days=i) for i in range((end - start).days + 1))
        self.assertEqual(actual, [first + timedelta(days=i) for i in range((last - first).days + 1)])
        self.assertIn(date(2024, 2, 29), actual)

    def test_registration_day_only(self):
        self.assertEqual(list(date_ranges(date(2026, 7, 15), date(2026, 7, 15))), [(date(2026, 7, 15), date(2026, 7, 15))])

    def test_invalid_range_fails(self):
        with self.assertRaises(ValueError):
            list(date_ranges(date(2026, 7, 16), date(2026, 7, 15)))

    def test_calendar_trims_padding_and_sorts(self):
        calendar = {"weeks": [{"contributionDays": [
            {"date": "2026-07-16", "contributionCount": 3},
            {"date": "2026-07-14", "contributionCount": 99},
            {"date": "2026-07-15", "contributionCount": 1},
            {"date": "2026-07-17", "contributionCount": 99},
        ]}]}
        self.assertEqual(parse_calendar(calendar, date(2026, 7, 15), date(2026, 7, 16)), [
            {"date": "2026-07-15", "count": 1}, {"date": "2026-07-16", "count": 3}])

    def test_missing_or_duplicate_days_fail(self):
        day = {"date": "2026-07-15", "contributionCount": 1}
        for items in [[], [day, day], [{**day, "contributionCount": -1}]]:
            with self.subTest(items=items), self.assertRaises(ValueError):
                parse_calendar({"weeks": [{"contributionDays": items}]}, date(2026, 7, 15), date(2026, 7, 15))

    def test_fetch_starts_at_created_at_and_extends_to_today(self):
        calls = []
        def fake_query(query, variables, token):
            calls.append(variables)
            if "createdAt" in query:
                return {"createdAt": "2023-12-30T07:30:02Z"}
            first, last = date.fromisoformat(variables["from"][:10]), date.fromisoformat(variables["to"][:10])
            items = [{"date": (first + timedelta(days=i)).isoformat(), "contributionCount": 1}
                     for i in range((last - first).days + 1)]
            return {"contributionsCollection": {"contributionCalendar": {"weeks": [{"contributionDays": items}]}}}
        now = datetime(2025, 1, 2, 10, 12, tzinfo=timezone.utc)
        history = fetch_history("test-user", "test-token", now=now, query=fake_query)
        self.assertEqual(history["start_date"], "2023-12-30")
        self.assertEqual(history["end_date"], "2025-01-02")
        self.assertEqual(calls[1]["from"], "2023-12-30T00:00:00+00:00")
        self.assertEqual(calls[-1]["to"], now.isoformat())
        self.assertEqual(len(history["days"]), 370)
        self.assertEqual(summarize(history["days"])["total"], 370)
        self.assertEqual(len({item["date"] for item in history["days"]}), 370)

    def test_summary_counts_streak_across_year_boundary(self):
        counts = [0, 2, 3, 4, 0, 8]
        days = [{"date": (date(2025, 12, 29) + timedelta(days=i)).isoformat(), "count": value}
                for i, value in enumerate(counts)]
        self.assertEqual(summarize(days), {"total": 17, "active_days": 4, "best_day": 8, "longest_streak": 3})

    def test_svg_keeps_all_years_and_exact_daily_counts(self):
        days = [{"date": (date(2023, 12, 30) + timedelta(days=i)).isoformat(), "count": i % 7}
                for i in range(370)]
        history = {"username": "name & test", "days": days, "start_date": days[0]["date"], "end_date": days[-1]["date"]}
        root = ET.fromstring(render_svg(history))
        columns = [node for node in root.iter() if "data-date" in node.attrib]
        self.assertEqual(len(columns), len(days))
        self.assertEqual(sum(int(node.attrib["data-count"]) for node in columns), summarize(days)["total"])
        self.assertEqual({node.attrib["data-date"] for node in columns}, {item["date"] for item in days})
        for year in (2023, 2024, 2025):
            self.assertTrue(any(node.attrib.get("aria-label") == f"{year} daily contributions" for node in root.iter()))
        # Every 3D face fits inside the SVG, including a complete leap year.
        for node in root.iter():
            if "points" in node.attrib:
                for point in node.attrib["points"].split():
                    x, y = map(float, point.split(","))
                    self.assertTrue(0 <= x <= 1200)
                    self.assertTrue(0 <= y <= int(root.attrib["height"]))

    def test_zero_activity_and_single_day_render(self):
        history = {"username": "new-user", "start_date": "2026-07-15", "end_date": "2026-07-15",
                   "days": [{"date": "2026-07-15", "count": 0}]}
        svg = render_svg(history)
        ET.fromstring(svg)
        self.assertNotIn("nan", svg)
        self.assertEqual(summarize(history["days"])["longest_streak"], 0)


if __name__ == "__main__":
    unittest.main()
