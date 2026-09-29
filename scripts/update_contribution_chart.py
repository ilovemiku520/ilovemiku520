#!/usr/bin/env python3
"""Render the profile's 3D contribution history from account creation to today.

Only Python's standard library is needed. All figures use the same daily GitHub
contribution counts; these are contributions, not lines of code or commit counts.
"""

from __future__ import annotations

import html
import json
import math
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
DAY = timedelta(days=1)
CALENDAR_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def graphql(query: str, variables: dict, token: str) -> dict:
    request = Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "github-profile-contribution-history",
        },
    )
    with urlopen(request, timeout=60) as response:
        result = json.load(response)
    if result.get("errors") or not result.get("data", {}).get("user"):
        raise RuntimeError(f"GitHub contribution query failed: {result.get('errors', 'user not found')}")
    return result["data"]["user"]


def date_ranges(start: date, end: date):
    """Small, disjoint ranges avoid API limits and preserve leap days."""
    if end < start:
        raise ValueError("The end date precedes account creation")
    while start <= end:
        stop = min(start + timedelta(days=89), end)
        yield start, stop
        start = stop + DAY


def parse_calendar(calendar: dict, start: date, end: date) -> list[dict]:
    """Reject incomplete results rather than publishing misleading zero counts."""
    counts = {}
    for week in calendar["weeks"]:
        for item in week["contributionDays"]:
            day = date.fromisoformat(item["date"])
            if start <= day <= end:
                count = item["contributionCount"]
                if type(count) is not int or count < 0 or day in counts:
                    raise ValueError(f"Invalid or duplicate contribution count for {day}")
                counts[day] = count
    expected = (end - start).days + 1
    if len(counts) != expected:
        raise ValueError(f"Incomplete calendar: expected {expected} days, received {len(counts)}")
    return [{"date": day.isoformat(), "count": counts[day]} for day in sorted(counts)]


def fetch_history(owner: str, token: str, now: datetime | None = None, query=graphql) -> dict:
    now = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    user = query("query($login: String!) { user(login: $login) { createdAt } }", {"login": owner}, token)
    created_at = user["createdAt"]
    start = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(UTC).date()
    days = []
    for first, last in date_ranges(start, now.date()):
        # Request whole UTC days, including the registration day and partial today.
        # Adjacent ranges do not share a date; calendar padding is filtered below.
        variables = {
            "login": owner,
            "from": datetime.combine(first, time.min, UTC).isoformat(),
            "to": min(datetime.combine(last, time(23, 59, 59), UTC), now).isoformat(),
        }
        data = query(CALENDAR_QUERY, variables, token)
        days.extend(parse_calendar(data["contributionsCollection"]["contributionCalendar"], first, last))
    return {
        "schema_version": 1,
        "username": owner,
        "account_created_at": created_at,
        "start_date": start.isoformat(),
        "end_date": now.date().isoformat(),
        "updated_at": now.isoformat(),
        "metric": "GitHub daily contributions visible to the workflow token; not lines of code",
        "days": days,
    }


def summarize(days: list[dict]) -> dict:
    longest = streak = 0
    for item in days:
        streak = streak + 1 if item["count"] else 0
        longest = max(longest, streak)
    return {
        "total": sum(item["count"] for item in days),
        "active_days": sum(item["count"] > 0 for item in days),
        "best_day": max((item["count"] for item in days), default=0),
        "longest_streak": longest,
    }


def render_svg(history: dict) -> str:
    days = history["days"]
    if not days:
        raise ValueError("Cannot render an empty contribution history")
    years = sorted({int(item["date"][:4]) for item in days})
    height = 434 + 438 * len(years)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{height}" viewBox="0 0 1200 {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{html.escape(history["username"])} — lifetime GitHub contributions</title>',
        f'<desc id="desc">Contributions from {history["start_date"]} to {history["end_date"]}, inclusive. '
        'Summary, cumulative trend and yearly 3D calendars use the same daily counts. Height and color show daily activity. Not lines of code.</desc>',
        '<style>text{font-family:system-ui,-apple-system,Segoe UI,sans-serif;fill:#d9eee8}'
        '.muted{fill:#93ada7;font-size:14px}.label{fill:#afd1c5;font-size:14px}'
        '.number{fill:#b6f2cc;font-size:32px;font-weight:650}.small{fill:#93ada7;font-size:12px}</style>',
        f'<rect width="1200" height="{height}" rx="22" fill="#0c1916"/>',
    ]

    def text(x, y, value, css="muted", extra=""):
        parts.append(f'<text x="{x}" y="{y}" class="{css}" {extra}>{html.escape(str(value))}</text>')

    def polygon(points, fill):
        coords = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        parts.append(f'<polygon points="{coords}" fill="{fill}"/>')

    text(36, 45, "GITHUB · SINCE JOINING", "label", 'letter-spacing="2"')
    text(36, 81, history["username"], "number")
    text(36, 111, f'{history["start_date"]} → {history["end_date"]} · All history · Updated daily')
    stats = summarize(days)
    cards = [("Total contributions", stats["total"]), ("Active days", stats["active_days"]),
             ("Best day", stats["best_day"]), ("Longest streak · days", stats["longest_streak"])]
    for index, (label, value) in enumerate(cards):
        x = 36 + index * 286
        parts.append(f'<rect x="{x}" y="137" width="270" height="91" rx="12" fill="#142a22"/>')
        text(x + 18, 166, label, "label")
        text(x + 18, 208, f"{value:,}", "number")

    text(36, 262, "Cumulative contributions", "label")
    running = 0
    points = [(36.0, 350.0)]
    for index, item in enumerate(days):
        running += item["count"]
        points.append((36 + 1128 * (index + 1) / len(days), 350 - 69 * running / max(1, stats["total"])))
    polygon(points + [(1164, 350)], "#183e2b")
    path = " ".join(f'{"M" if i == 0 else "L"}{x:.2f},{y:.2f}' for i, (x, y) in enumerate(points))
    parts.append(f'<path d="{path}" fill="none" stroke="#63d990" stroke-width="2.5"/>')
    text(36, 374, history["start_date"], "small")
    text(1164, 374, f'{history["end_date"]} · {stats["total"]:,} total', "small", 'text-anchor="end"')

    # Use one shared scale for every year, so equal counts have equal heights/colors.
    max_count = max(1, stats["best_day"])
    palette = [("#233d32", "#182b23", "#1b3229"), ("#3b7953", "#285038", "#306344"),
               ("#4caa70", "#34754d", "#408c5d"), ("#67d990", "#409560", "#50b976"),
               ("#b6f2aa", "#6aa765", "#8bce82")]
    for index, year in enumerate(years):
        top = 398 + index * 438
        subset = [item for item in days if int(item["date"][:4]) == year]
        annual = summarize(subset)
        first = date.fromisoformat(subset[0]["date"])
        last = date.fromisoformat(subset[-1]["date"])
        sunday = first - timedelta(days=(first.weekday() + 1) % 7)
        weeks = (last - sunday).days // 7 + 1
        # A short first/last year stays centered. Full years fit the same panel.
        dx = min(27.0, 1060 / (weeks + 7))
        dy = min(dx * 0.44, 244 / (weeks + 7))
        left = 600 - (weeks + 7) * dx / 2
        base_y = top + 155
        parts.append(f'<g aria-label="{year} daily contributions">')
        parts.append(f'<rect x="20" y="{top}" width="1160" height="420" rx="14" fill="#10231c"/>')
        text(42, top + 37, year, "number")
        text(42, top + 63, f"{first} → {last}", "small")
        text(1158, top + 36, f'{annual["total"]:,} contributions · {annual["active_days"]} active days', "label", 'text-anchor="end"')
        # Render far rows first to keep neighboring 3D columns in proper depth order.
        ordered = sorted(subset, key=lambda item: (
            (date.fromisoformat(item["date"]) - sunday).days // 7
            + (date.fromisoformat(item["date"]).weekday() + 1) % 7))
        for item in ordered:
            current = date.fromisoformat(item["date"])
            week = (current - sunday).days // 7
            weekday = (current.weekday() + 1) % 7
            x = left + (week + 6 - weekday) * dx
            y = base_y + (week + weekday) * dy
            count = item["count"]
            ratio = math.log1p(count) / math.log1p(max_count)
            bar_height = 3 + 72 * ratio
            level = 0 if count == 0 else max(1, math.ceil(4 * ratio))
            cap, side_l, side_r = palette[level]
            w, d = dx * 0.91, dy * 0.91
            parts.append(f'<g data-date="{current}" data-count="{count}"><title>{current}: {count} contributions</title>')
            polygon([(x-w, y), (x, y+d), (x, y+d-bar_height), (x-w, y-bar_height)], side_l)
            polygon([(x, y+d), (x+w, y), (x+w, y-bar_height), (x, y+d-bar_height)], side_r)
            polygon([(x, y-d-bar_height), (x+w, y-bar_height), (x, y+d-bar_height), (x-w, y-bar_height)], cap)
            parts.append('</g>')
        text(42, top + 395, "Each column = one day · Height & color = daily contributions", "small")
        text(968, top + 395, "Less", "small")
        for level, colors in enumerate(palette):
            parts.append(f'<rect x="{1008 + level * 20}" y="{top + 384}" width="14" height="14" rx="3" fill="{colors[0]}"/>')
        text(1114, top + 395, "More", "small")
        parts.append('</g>')

    text(36, height - 17, "GitHub contribution counts · UTC date range · Contributions are not lines of code", "small")
    text(1164, height - 17, "Full history · No rolling window", "small", 'text-anchor="end"')
    parts.append('</svg>')
    return "\n".join(parts) + "\n"


def main():
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "ilovemiku520")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise SystemExit("GITHUB_TOKEN is required to read GitHub contribution history")
    history = fetch_history(owner, token)
    svg = render_svg(history)  # Validate/render everything before replacing outputs.
    svg_path = ROOT / "profile-3d-contrib" / "profile-green.svg"
    data_path = ROOT / "assets" / "contribution-history.json"
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text(svg, encoding="utf-8")
    data_path.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {owner}: {history['start_date']} to {history['end_date']}, {summarize(history['days'])['total']:,} contributions")


if __name__ == "__main__":
    main()
