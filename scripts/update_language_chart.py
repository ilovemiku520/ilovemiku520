#!/usr/bin/env python3
"""Build the profile language chart from public, non-fork GitHub repositories."""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen


OWNER = os.environ.get("GITHUB_REPOSITORY_OWNER", "ilovemiku520")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUTPUT = Path(__file__).resolve().parents[1] / "assets" / "language-usage.svg"

COLORS = {
    "Python": "#3572A5",
    "TypeScript": "#3178C6",
    "PowerShell": "#012456",
    "JavaScript": "#F1E05A",
    "CSS": "#563D7C",
    "HTML": "#E34C26",
    "R": "#198CE7",
    "Shell": "#89E051",
    "Dockerfile": "#384D54",
    "Jupyter Notebook": "#DA5B0B",
    "Other": "#8C959F",
}


def github_json(url: str):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{OWNER}-profile-language-chart",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    with urlopen(Request(url, headers=headers), timeout=30) as response:
        return json.load(response)


def public_source_repositories() -> list[dict]:
    repositories: list[dict] = []
    page = 1
    while True:
        batch = github_json(
            f"https://api.github.com/users/{OWNER}/repos"
            f"?type=owner&sort=full_name&per_page=100&page={page}"
        )
        repositories.extend(
            repo
            for repo in batch
            if not repo.get("fork") and not repo.get("archived") and not repo.get("disabled")
        )
        if len(batch) < 100:
            return repositories
        page += 1


def aggregate_languages() -> dict[str, int]:
    totals: dict[str, int] = {}
    for repository in public_source_repositories():
        for language, byte_count in github_json(repository["languages_url"]).items():
            totals[language] = totals.get(language, 0) + int(byte_count)
    if not totals:
        raise RuntimeError("GitHub returned no language data for public source repositories.")
    return totals


def chart_entries(totals: dict[str, int]) -> list[tuple[str, float]]:
    total_bytes = sum(totals.values())
    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    entries = [(name, count * 100 / total_bytes) for name, count in ranked[:5]]
    other_bytes = sum(count for _, count in ranked[5:])
    if other_bytes:
        entries.append(("Other", other_bytes * 100 / total_bytes))
    return entries


def render_svg(entries: list[tuple[str, float]]) -> str:
    description = ", ".join(f"{name} {share:.1f} percent" for name, share in entries) + "."
    arcs: list[str] = []
    legend: list[str] = []
    offset = 0.0
    for index, (name, share) in enumerate(entries):
        color = COLORS.get(name, "#8C959F")
        safe_name = html.escape(name)
        arcs.append(
            f'    <circle cx="145" cy="145" r="88" pathLength="100" '
            f'stroke="{color}" stroke-dasharray="{share:.4f} {100 - share:.4f}" '
            f'stroke-dashoffset="{-offset:.4f}" />'
        )
        y = index * 36
        legend.extend(
            [
                f'    <circle cx="7" cy="{y + 7}" r="7" fill="{color}" />',
                f'    <text x="25" y="{y + 12}" class="label">{safe_name}</text>',
                f'    <text x="235" y="{y + 12}" text-anchor="end" class="value">{share:.1f}%</text>',
                "",
            ]
        )
        offset += share

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="620" height="300" viewBox="0 0 620 300" role="img" aria-labelledby="title desc">
  <title id="title">Language usage across public repositories</title>
  <desc id="desc">{html.escape(description)}</desc>
  <style>
    .label {{ font: 600 15px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #24292f; }}
    .value {{ font: 14px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #57606a; }}
    .caption {{ font: 12px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #6e7781; }}
    @media (prefers-color-scheme: dark) {{
      .label {{ fill: #f0f6fc; }}
      .value {{ fill: #b1bac4; }}
      .caption {{ fill: #8c959f; }}
    }}
  </style>

  <g transform="rotate(-90 145 145)" fill="none" stroke-width="48">
    <circle cx="145" cy="145" r="88" pathLength="100" stroke="#d8dee4" opacity="0.35" />
{chr(10).join(arcs)}
  </g>

  <text x="145" y="139" text-anchor="middle" class="label">Public repos</text>
  <text x="145" y="161" text-anchor="middle" class="value">language mix</text>

  <g transform="translate(300 47)">
{chr(10).join(legend).rstrip()}
  </g>

  <text x="310" y="278" text-anchor="middle" class="caption">Updated automatically from GitHub Linguist byte counts</text>
</svg>
'''


def main() -> None:
    svg = render_svg(chart_entries(aggregate_languages()))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != svg:
        OUTPUT.write_text(svg, encoding="utf-8", newline="\n")
        print(f"Updated {OUTPUT}")
    else:
        print("Language chart is already current.")


if __name__ == "__main__":
    main()
