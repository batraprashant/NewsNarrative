#!/usr/bin/env python3
"""
Generate RELEASE_NOTES.md from git log.

Groups commits by date, categorises them by prefix keyword, and writes a
clean Markdown changelog. Run locally or via the release-notes GitHub Action.

Usage:
    python scripts/generate_release_notes.py
"""

import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
OUTPUT_FILE = REPO_ROOT / "RELEASE_NOTES.md"

# Commit subject prefixes → category label
CATEGORY_RULES = [
    (("fix", "strip", "revert", "hotfix"),           "Bug Fixes"),
    (("add", "convert", "implement", "introduce"),    "Features"),
    (("upgrade", "update", "switch", "migrate"),      "Changes"),
    (("apply", "harden", "improve", "refactor"),      "Improvements"),
    (("docs", "readme", "document"),                  "Documentation"),
    (("ci", "workflow", "lint", "test", "coverage"),  "CI / Testing"),
]
DEFAULT_CATEGORY = "Other"


def categorise(subject: str) -> str:
    lower = subject.lower()
    for keywords, label in CATEGORY_RULES:
        if any(lower.startswith(kw) for kw in keywords):
            return label
    return DEFAULT_CATEGORY


def get_commits() -> list[dict]:
    result = subprocess.run(
        ["git", "log", "--format=%H|%aI|%s", "--no-merges"],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    commits = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        sha, date_str, subject = parts
        subject = subject.strip()
        # Skip automated bot commits
        if "[skip ci]" in subject.lower():
            continue
        dt = datetime.fromisoformat(date_str.strip()).astimezone(timezone.utc)
        commits.append(
            {
                "sha": sha[:7],
                "date": dt.date(),
                "subject": subject.rstrip("."),
                "category": categorise(subject),
            }
        )
    return commits


def build_markdown(commits: list[dict]) -> str:
    # Group commits by date (newest first)
    by_date: dict = defaultdict(lambda: defaultdict(list))
    for c in commits:
        by_date[c["date"]][c["category"]].append(c)

    category_order = [
        "Features", "Improvements", "Changes",
        "Bug Fixes", "CI / Testing", "Documentation", "Other",
    ]

    lines = [
        "# Release Notes",
        "",
        "> Auto-generated from git history. Updated on every push to `main`.",
        "",
    ]

    for date in sorted(by_date.keys(), reverse=True):
        lines.append(f"## {date.strftime('%B %d, %Y')}")
        lines.append("")
        categories = by_date[date]
        for cat in category_order:
            if cat not in categories:
                continue
            lines.append(f"### {cat}")
            for c in categories[cat]:
                lines.append(f"- {c['subject']} (`{c['sha']}`)")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main():
    commits = get_commits()
    if not commits:
        print("No commits found.", file=sys.stderr)
        sys.exit(1)

    content = build_markdown(commits)
    OUTPUT_FILE.write_text(content, encoding="utf-8")
    print(f"Written {len(commits)} commits to {OUTPUT_FILE.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
