"""Refresh stars.json with current stargazer counts per widget.

Reads widgets.json, parses the GitHub owner/repo from each entry's
release.tarball_url (https://github.com/{owner}/{repo}/archive/...),
fetches /repos/{owner}/{repo} from the GitHub API, and writes
stars.json with:

    {
      "fetched_at": "<ISO 8601 UTC>",
      "stars": {"<widget_id>": <int>, ...}
    }

Individual repo failures (404, rate limit, network blip) skip that
widget without poisoning the rest. Only rewrites stars.json when the
actual counts changed, so the repo doesn't churn a no-op commit per
hour. Authenticated via GITHUB_TOKEN (the Actions runner's built-in
token), 5000/hr ceiling — plenty for hourly refresh of a few hundred
widgets.

Run by .github/workflows/refresh-stars.yml.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime

TARBALL_RE = re.compile(r"https://github\.com/([^/]+)/([^/]+)/archive/")


def fetch_stars(owner: str, name: str, token: str) -> int | None:
    url = f"https://api.github.com/repos/{owner}/{name}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "tesserae-widgets-refresh-stars",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            data = json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as err:
        print(f"  {owner}/{name}: skipped ({err})", file=sys.stderr)
        return None
    count = data.get("stargazers_count")
    return int(count) if isinstance(count, int) else None


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("GITHUB_TOKEN env var required", file=sys.stderr)
        return 1

    with open("widgets.json", encoding="utf-8") as f:
        catalog = json.load(f)
    widgets = catalog.get("widgets", [])

    stars: dict[str, int] = {}
    for w in widgets:
        widget_id = w.get("id")
        tarball = (w.get("release") or {}).get("tarball_url", "")
        m = TARBALL_RE.match(tarball)
        if not (widget_id and m):
            continue
        owner, name = m.group(1), m.group(2)
        print(f"  {widget_id} → {owner}/{name}...", end=" ", flush=True)
        count = fetch_stars(owner, name, token)
        if count is not None:
            stars[widget_id] = count
            print(f"{count}")

    sorted_stars = dict(sorted(stars.items()))

    # Only rewrite stars.json when the actual counts change, so the
    # `fetched_at` timestamp doesn't churn a no-op commit every hour.
    try:
        with open("stars.json", encoding="utf-8") as f:
            existing = json.load(f).get("stars", {})
    except (FileNotFoundError, json.JSONDecodeError):
        existing = {}
    if existing == sorted_stars:
        print(f"No star changes for {len(sorted_stars)} widgets; skipping write.")
        return 0

    payload = {
        "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stars": sorted_stars,
    }
    with open("stars.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    print(f"Wrote stars for {len(sorted_stars)}/{len(widgets)} widgets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
