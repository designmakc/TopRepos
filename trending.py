"""Daily digest of fastest-growing GitHub repos -> digest.md.

Velocity = stars gained since yesterday's snapshot (data/stars.json).
Repos not in the snapshot yet (first run / newly found) get an estimate: stars / age in days.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api.github.com/search/repositories"
SNAP = "data/stars.json"
TOP = 15


def search(q):
    url = f"{API}?{urllib.parse.urlencode({'q': q, 'sort': 'stars', 'order': 'desc', 'per_page': 100})}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
    })
    with urllib.request.urlopen(req) as r:
        return json.load(r)["items"]


def translate(text):
    """To Russian via free MyMemory API; on any failure keep the original."""
    if not text:
        return text
    url = "https://api.mymemory.translated.net/get?" + urllib.parse.urlencode({"q": text[:500], "langpair": "autodetect|ru"})
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            d = json.load(r)
        return d["responseData"]["translatedText"] if d.get("responseStatus") == 200 else text
    except Exception:
        return text


def score(stars, prev, age_days):
    return stars - prev if prev is not None else stars / max(age_days, 1)


def main():
    now = datetime.now(timezone.utc)
    # ponytail: only repos <180d old are watched; old giants rarely "explode". Widen the query if needed.
    queries = (
        f"created:>{(now - timedelta(days=30)).date()} stars:>100",
        f"created:>{(now - timedelta(days=180)).date()} stars:>1000",
    )
    repos = {r["full_name"]: r for q in queries for r in search(q)}

    try:
        with open(SNAP) as f:
            prev = json.load(f)
    except FileNotFoundError:
        prev = {}

    rows = []
    for name, r in repos.items():
        age = (now - datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))).days
        p = prev.get(name)
        rows.append((score(r["stargazers_count"], p, age), p is None, name, r, age))
    rows.sort(key=lambda x: -x[0])

    out = [
        f"# Быстрорастущие репозитории GitHub - {now.date()}",
        "",
        "Δ = прирост звёзд за 24 ч. `~` = оценка (звёзды / возраст), репозиторий ещё не отслеживался.",
        "",
        "| # | Репозиторий | Звёзды | Δ/день | Возраст (дн) | Язык | Описание |",
        "|---|------|-------|-------|---------|------|-------------|",
    ]
    for i, (s, est, name, r, age) in enumerate(rows[:TOP], 1):
        desc = translate(r["description"] or "").replace("|", "/").replace("\n", " ")[:120]
        out.append(
            f"| {i} | [{name}]({r['html_url']}) | {r['stargazers_count']} | "
            f"{'~' if est else '+'}{s:.0f} | {age} | {r['language'] or '-'} | {desc} |"
        )

    with open("digest.md", "w") as f:
        f.write("\n".join(out) + "\n")
    os.makedirs("data", exist_ok=True)
    with open(SNAP, "w") as f:
        json.dump({n: r["stargazers_count"] for n, r in repos.items()}, f)


if __name__ == "__main__":
    if "--test" in sys.argv:
        assert score(150, 100, 5) == 50
        assert score(150, None, 5) == 30
        assert score(10, None, 0) == 10
        print("ok")
    else:
        main()
